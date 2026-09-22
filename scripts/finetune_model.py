#!/usr/bin/env python3
\"\"\"Domain-specific embedding model fine-tuning script.

This script enables lightweight fine-tuning of embedding models on local data
(code, documentation, logs) to improve semantic relevance for a specific domain.

Features:
- Lightweight fine-tuning using sentence-transformers
- Support for unsupervised SimCSE (Simple Contrastive Learning of Sentence Embeddings)
- Support for Matryoshka Representation Learning (MRL) for fast searches
- Automatic export to ONNX for use with FastEmbed or LocalModelEmbedder
- Synthetic query generation (placeholder for LLM-based generation)

Usage:
    python scripts/finetune_model.py --data-dir ./docs --output-dir ./models/my-domain-model
\"\"\"

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
from sentence_transformers import SentenceTransformer, InputExample, losses, models
from torch.utils.data import DataLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SyntheticDataGenerator:
    \"\"\"Generate training data from local files.\"\"\"
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        
    def collect_texts(self, extensions: List[str] = [".md", ".py", ".txt"]) -> List[str]:
        \"\"\"Collect all text chunks from the data directory.\"\"\"
        texts = []
        for ext in extensions:
            for path in self.data_dir.rglob(f"*{ext}"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                        # Simple chunking by paragraphs/functions for now
                        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 20]
                        texts.extend(chunks)
                except Exception as e:
                    logger.warning("Failed to read %s: %s", path, e)
        return texts

    def create_simcse_examples(self, texts: List[str]) -> List[InputExample]:
        \"\"\"Create examples for unsupervised SimCSE.
        
        SimCSE uses the same sentence twice in a pair; the model's dropout
        creates two different embeddings, and the loss forces them together.
        \"\"\"
        return [InputExample(texts=[text, text]) for text in texts]


def train_model(
    base_model_name: str,
    train_examples: List[InputExample],
    output_path: Path,
    epochs: int = 1,
    batch_size: int = 16,
    use_mrl: bool = False,
    mrl_dimensions: List[int] = [64, 128, 256, 384, 512, 768]
) -> SentenceTransformer:
    \"\"\"Fine-tune the model.\"\"\"
    logger.info("Loading base model: %s", base_model_name)
    model = SentenceTransformer(base_model_name)
    
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)
    
    # Use MultipleNegativesRankingLoss for SimCSE/Contrastive learning
    train_loss = losses.MultipleNegativesRankingLoss(model)
    
    if use_mrl:
        logger.info("Enabling Matryoshka Representation Learning (MRL)")
        # Wrap the loss with MatryoshkaLoss
        train_loss = losses.MatryoshkaLoss(model, train_loss, mrl_dimensions)

    logger.info("Starting fine-tuning for %d epochs...", epochs)
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=int(len(train_dataloader) * 0.1),
        output_path=str(output_path)
    )
    
    return model


def export_to_onnx(model_path: Path, output_path: Path, quantize: bool = False):
    \"\"\"Export the fine-tuned model to ONNX format.\"\"\"
    logger.info("Exporting model to ONNX...")
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
        
        # Load the fine-tuned model
        model = ORTModelForFeatureExtraction.from_pretrained(model_path, export=True)
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        
        # Save to output directory
        model.save_pretrained(output_path)
        tokenizer.save_pretrained(output_path)
        
        if quantize:
            logger.info("Quantizing model to INT8...")
            # Simple dynamic quantization
            from optimum.onnxruntime import ORTQuantizer
            from optimum.onnxruntime.configuration import QuantizationConfig
            
            quantizer = ORTQuantizer.from_pretrained(output_path)
            q_config = QuantizationConfig(is_static=False, format="QDQ")
            quantizer.quantize(save_dir=output_path, quantization_config=q_config)
            
        logger.info("ONNX export complete: %s", output_path)
    except ImportError:
        logger.error("optimum or onnxruntime not found. Skipping ONNX export.")
    except Exception as e:
        logger.error("ONNX export failed: %s", e)


def save_metadata(model_dir: Path, model_id: str, dimensions: int):
    \"\"\"Save metadata for LocalModelEmbedder compatibility.\"\"\"
    # We need to reach into agent-vault to use the metadata class if possible
    # but for a standalone script, we can just write the JSON.
    metadata = {
        "model_id": model_id,
        "format": "onnx",
        "dimensions": dimensions,
        "max_sequence_length": 512,
        "tokenizer_type": "BertTokenizer",
        "normalize_embeddings": True,
        "pooling_mode": "mean",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_url": None
    }
    
    with open(model_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Fine-tune an embedding model on local data.")
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory containing text data for training")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to save the fine-tuned model")
    parser.add_argument("--base-model", type=str, default="BAAI/bge-small-en-v1.5", help="Base model to fine-tune")
    parser.add_argument("--epochs", type=int, default=1, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Training batch size")
    parser.add_argument("--mrl", action="store_true", help="Enable Matryoshka Representation Learning")
    parser.add_argument("--quantize", action="store_true", help="Quantize the resulting ONNX model")
    
    args = parser.parse_args()
    
    if not args.data_dir.exists():
        logger.error("Data directory not found: %s", args.data_dir)
        return 1

    # 1. Collect and prepare data
    generator = SyntheticDataGenerator(args.data_dir)
    texts = generator.collect_texts()
    if not texts:
        logger.error("No training data found in %s", args.data_dir)
        return 1
    
    logger.info("Collected %d text chunks for fine-tuning", len(texts))
    train_examples = generator.create_simcse_examples(texts)
    
    # 2. Train/Fine-tune
    temp_model_path = args.output_dir / "pytorch"
    model = train_model(
        base_model_name=args.base_model,
        train_examples=train_examples,
        output_path=temp_model_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        use_mrl=args.mrl
    )
    
    # 3. Export to ONNX
    onnx_path = args.output_dir / "onnx"
    export_to_onnx(temp_model_path, onnx_path, quantize=args.quantize)
    
    # 4. Save metadata
    # Get dimensions from model
    dimensions = model.get_sentence_embedding_dimension()
    save_metadata(onnx_path, f"domain-tuned-{args.base_model}", dimensions)
    
    logger.info("Done! Model saved to %s", onnx_path)
    logger.info("To use this model, configure 'local_model' or 'fastembed' to point to this directory.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
