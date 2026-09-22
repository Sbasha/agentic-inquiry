#!/usr/bin/env python3
"""Model conversion script for agent_vault.

This script downloads models from HuggingFace Hub and converts them to
ONNX format for use with LocalModelEmbedder. It handles model download,
conversion, tokenizer extraction, and metadata generation.

Usage:
    python scripts/convert_model.py <model_id> [options]

Examples:
    # Convert a model to ONNX
    python scripts/convert_model.py sentence-transformers/all-MiniLM-L6-v2

    # Convert with quantization
    python scripts/convert_model.py sentence-transformers/all-MiniLM-L6-v2 --quantize

    # Force re-conversion of existing model
    python scripts/convert_model.py sentence-transformers/all-MiniLM-L6-v2 --force

    # Dry run to preview conversion
    python scripts/convert_model.py sentence-transformers/all-MiniLM-L6-v2 --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def detect_workspace_root() -> Path:
    """Detect the workspace root directory.
    
    Looks for agent-vault.yaml or config/default.yaml to identify workspace root.
    Falls back to current directory if not found.
    
    Returns:
        Path to workspace root directory
    """
    current = Path.cwd()
    
    # Check current directory and parents for workspace markers
    for path in [current] + list(current.parents):
        if (path / "agent-vault.yaml").exists() or (path / "config" / "default.yaml").exists():
            logger.debug("Detected workspace root: %s", path)
            return path
    
    # Fall back to current directory
    logger.warning(
        "Could not detect workspace root. Using current directory: %s",
        current
    )
    return current


def setup_output_directory(workspace_root: Path, model_id: str) -> Path:
    """Set up output directory for converted model.
    
    Args:
        workspace_root: Root directory of workspace
        model_id: HuggingFace model identifier
        
    Returns:
        Path to output directory for this model
    """
    # Create models directory in workspace
    models_dir = workspace_root / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # Create model-specific directory
    # Convert model_id to safe directory name
    safe_name = model_id.replace("/", "--")
    output_dir = models_dir / safe_name
    
    logger.debug("Output directory: %s", output_dir)
    return output_dir


def convert_to_onnx(
    model_dir: Path,
    model_id: str,
    *,
    quantize: bool = False
) -> Path:
    """Convert model to ONNX format.
    
    Args:
        model_dir: Directory containing the downloaded model
        model_id: Original HuggingFace model identifier
        quantize: Whether to quantize the model
        
    Returns:
        Path to the ONNX model file
        
    Raises:
        RuntimeError: If conversion fails
    """
    from datetime import datetime, timezone
    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer
    import numpy as np
    
    logger.info("Converting model to ONNX format...")
    
    try:
        # Load and convert model to ONNX
        logger.info("Loading model for ONNX conversion...")
        logger.info("  [1/5] Loading PyTorch model...")
        
        # Configure quantization if requested
        if quantize:
            logger.info("  Quantization enabled (INT8)")
            from optimum.onnxruntime.configuration import QuantizationConfig
            
            quantization_config = QuantizationConfig(
                is_static=False,  # Dynamic quantization
                format="QDQ",  # Quantize-Dequantize format
                per_channel=True,
                reduce_range=False,
                operators_to_quantize=["MatMul", "Add"]
            )
        else:
            quantization_config = None
        
        ort_model = ORTModelForFeatureExtraction.from_pretrained(
            model_dir,
            export=True,  # Export to ONNX if not already
            provider="CPUExecutionProvider"
        )
        
        logger.info("  [2/5] Converting to ONNX format...")
        
        # Save ONNX model
        onnx_path = model_dir / "model.onnx"
        ort_model.save_pretrained(model_dir)
        
        # Apply quantization if requested
        if quantize:
            logger.info("  [3/5] Applying quantization...")
            try:
                from optimum.onnxruntime import ORTQuantizer
                
                quantizer = ORTQuantizer.from_pretrained(model_dir)
                quantizer.quantize(
                    save_dir=model_dir,
                    quantization_config=quantization_config
                )
                logger.info("  Quantization applied successfully")
            except Exception as e:
                logger.warning("  Quantization failed, continuing with unquantized model: %s", e)
        else:
            logger.info("  [3/5] Skipping quantization")
        
        logger.info("  [4/5] ONNX model saved to %s", onnx_path)
        
        # Load tokenizer for metadata extraction
        logger.info("  [5/5] Extracting metadata...")
        tokenizer = AutoTokenizer.from_pretrained(model_dir)
        
        # Detect embedding dimensions by running a test inference
        logger.info("Detecting embedding dimensions...")
        test_text = ["This is a test sentence."]
        inputs = tokenizer(test_text, return_tensors="np", padding=True, truncation=True)
        outputs = ort_model(**inputs)
        
        # Get embeddings from model output
        # Most models output last_hidden_state
        if hasattr(outputs, "last_hidden_state"):
            embeddings = outputs.last_hidden_state
        elif isinstance(outputs, dict) and "last_hidden_state" in outputs:
            embeddings = outputs["last_hidden_state"]
        else:
            # Try to get first output
            embeddings = outputs[0] if isinstance(outputs, (list, tuple)) else outputs
        
        # Apply mean pooling to get sentence embedding
        attention_mask = inputs["attention_mask"]
        attention_mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(np.float32)
        sum_embeddings = np.sum(embeddings * attention_mask_expanded, axis=1)
        sum_mask = np.sum(attention_mask_expanded, axis=1)
        sum_mask = np.clip(sum_mask, a_min=1e-9, a_max=None)
        sentence_embedding = sum_embeddings / sum_mask
        
        dimensions = sentence_embedding.shape[-1]
        logger.info("Detected embedding dimensions: %d", dimensions)
        
        # Get max sequence length
        max_length = tokenizer.model_max_length
        if max_length > 1_000_000:  # Some tokenizers return very large values
            max_length = 512  # Use reasonable default
        
        # Determine tokenizer type
        tokenizer_type = type(tokenizer).__name__
        
        # Create metadata
        from agent_vault.embeddings.local_model import ModelMetadata
        
        metadata = ModelMetadata(
            model_id=model_id,
            format="onnx",
            dimensions=int(dimensions),
            max_sequence_length=int(max_length),
            tokenizer_type=tokenizer_type,
            normalize_embeddings=True,  # Most sentence transformers normalize
            pooling_mode="mean",  # Default to mean pooling
            created_at=datetime.now(timezone.utc).isoformat(),
            source_url=f"https://huggingface.co/{model_id}"
        )
        
        # Save metadata
        metadata_path = model_dir / "metadata.json"
        metadata.save(metadata_path)
        logger.info("Metadata saved to %s", metadata_path)
        
        # Validate conversion by testing the model
        logger.info("Validating converted model...")
        validate_converted_model(model_dir)
        
        logger.info("ONNX conversion complete")
        return onnx_path
        
    except Exception as e:
        logger.error("ONNX conversion failed: %s", e, exc_info=True)
        raise RuntimeError(f"ONNX conversion failed: {e}") from e


def validate_converted_model(model_dir: Path) -> None:
    """Validate that the converted model works correctly.
    
    Args:
        model_dir: Directory containing the converted model
        
    Raises:
        RuntimeError: If validation fails
    """
    logger.info("Running validation tests...")
    
    try:
        from agent_vault.embeddings.local_model import LocalModelEmbedder
        
        # Create embedder instance
        embedder = LocalModelEmbedder(model_path=model_dir)
        
        # Test embedding generation
        test_texts = [
            "This is a test sentence.",
            "Another test sentence for validation."
        ]
        
        embeddings = embedder.generate(test_texts)
        
        # Validate embeddings
        if len(embeddings) != len(test_texts):
            raise RuntimeError(
                f"Expected {len(test_texts)} embeddings, got {len(embeddings)}"
            )
        
        # Check dimensions
        expected_dims = embedder.ndims()
        for i, emb in enumerate(embeddings):
            if len(emb) != expected_dims:
                raise RuntimeError(
                    f"Embedding {i} has {len(emb)} dimensions, expected {expected_dims}"
                )
        
        logger.info("Validation successful!")
        logger.info("  - Generated %d embeddings", len(embeddings))
        logger.info("  - Embedding dimensions: %d", expected_dims)
        
    except Exception as e:
        logger.error("Validation failed: %s", e, exc_info=True)
        raise RuntimeError(f"Model validation failed: {e}") from e


def cleanup_on_failure(output_dir: Path) -> None:
    """Clean up output directory on failure.
    
    Args:
        output_dir: Directory to clean up
    """
    import shutil
    
    if output_dir.exists():
        logger.info("Cleaning up incomplete conversion at %s", output_dir)
        try:
            shutil.rmtree(output_dir)
            logger.info("Cleanup complete")
        except Exception as e:
            logger.warning("Failed to clean up directory: %s", e)


def download_model(
    model_id: str,
    output_dir: Path,
    *,
    force: bool = False,
    token: str | None = None
) -> bool:
    """Download model from HuggingFace Hub.
    
    Args:
        model_id: HuggingFace model identifier
        output_dir: Directory to download model to
        force: Force re-download even if model exists
        token: HuggingFace authentication token for private models
        
    Returns:
        True if model was downloaded, False if skipped (already exists)
        
    Raises:
        RuntimeError: If download fails
    """
    from transformers import AutoModel, AutoTokenizer
    import shutil
    
    # Check if model already exists
    if output_dir.exists() and not force:
        # Check for key files to determine if model is complete
        required_files = ["config.json"]
        has_all_files = all((output_dir / f).exists() for f in required_files)
        
        if has_all_files:
            logger.info(
                "Model already exists at %s (use --force to re-download)",
                output_dir
            )
            return False
        else:
            logger.warning(
                "Model directory exists but appears incomplete. Re-downloading..."
            )
    
    # Clean up existing directory if forcing re-download
    if output_dir.exists() and force:
        logger.info("Removing existing model directory...")
        shutil.rmtree(output_dir)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Downloading model '%s' from HuggingFace Hub...", model_id)
    
    try:
        # Download model
        logger.info("  [1/2] Downloading model weights...")
        logger.info("  This may take a few minutes depending on model size...")
        
        model = AutoModel.from_pretrained(
            model_id,
            token=token,
            trust_remote_code=False  # Security: don't execute remote code
        )
        
        # Save model to output directory
        model.save_pretrained(output_dir)
        logger.info("  Model weights saved to %s", output_dir)
        
        # Download tokenizer
        logger.info("  [2/2] Downloading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            token=token,
            trust_remote_code=False
        )
        
        # Save tokenizer to output directory
        tokenizer.save_pretrained(output_dir)
        logger.info("  Tokenizer saved to %s", output_dir)
        
        logger.info("Model download complete")
        return True
        
    except Exception as e:
        logger.error("Failed to download model: %s", e, exc_info=True)
        # Clean up on failure
        cleanup_on_failure(output_dir)
        raise RuntimeError(f"Model download failed: {e}") from e


def main() -> int:
    """Main entry point for model conversion script.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    parser = argparse.ArgumentParser(
        description="Convert HuggingFace models to ONNX format for agent-vault",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "model_id",
        type=str,
        help="HuggingFace model identifier (e.g., sentence-transformers/all-MiniLM-L6-v2)"
    )
    
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=None,
        help="Output directory for converted model (default: workspace/models/<model_name>)"
    )
    
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force re-conversion even if model already exists"
    )
    
    parser.add_argument(
        "-q", "--quantize",
        action="store_true",
        help="Quantize model weights for smaller size (experimental)"
    )
    
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Preview conversion without executing"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="HuggingFace authentication token for private models"
    )
    
    args = parser.parse_args()
    
    # Configure logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    # Detect workspace root
    workspace_root = detect_workspace_root()
    logger.info("Workspace root: %s", workspace_root)
    
    # Set up output directory
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = setup_output_directory(workspace_root, args.model_id)
    
    logger.info("Model ID: %s", args.model_id)
    logger.info("Output directory: %s", output_dir)
    
    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("Would convert model '%s' to: %s", args.model_id, output_dir)
        logger.info("Options: quantize=%s, force=%s", args.quantize, args.force)
        return 0
    
    try:
        # Step 1: Download model from HuggingFace Hub
        logger.info("=" * 60)
        logger.info("Step 1: Downloading model from HuggingFace Hub")
        logger.info("=" * 60)
        
        downloaded = download_model(
            args.model_id,
            output_dir,
            force=args.force,
            token=args.token
        )
        
        if not downloaded and not args.force:
            logger.info("Model already exists. Skipping conversion.")
            logger.info("Use --force to re-convert existing model.")
            return 0
        
        # Step 2: Convert to ONNX format
        logger.info("=" * 60)
        logger.info("Step 2: Converting to ONNX format")
        logger.info("=" * 60)
        
        onnx_path = convert_to_onnx(
            output_dir,
            args.model_id,
            quantize=args.quantize
        )
        
        # Success!
        logger.info("=" * 60)
        logger.info("Conversion complete!")
        logger.info("=" * 60)
        logger.info("Model saved to: %s", output_dir)
        logger.info("ONNX model: %s", onnx_path)
        logger.info("")
        logger.info("To use this model in agent-vault, configure:")
        logger.info("  embedding:")
        logger.info("    provider: local")
        logger.info("    local_model:")
        logger.info("      model_path: %s", output_dir.relative_to(workspace_root))
        logger.info("")
        
        # Display model info
        metadata_path = output_dir / "metadata.json"
        if metadata_path.exists():
            from agent_vault.embeddings.local_model import ModelMetadata
            metadata = ModelMetadata.load(metadata_path)
            logger.info("Model Information:")
            logger.info("  Model ID: %s", metadata.model_id)
            logger.info("  Format: %s", metadata.format)
            logger.info("  Dimensions: %d", metadata.dimensions)
            logger.info("  Max sequence length: %d", metadata.max_sequence_length)
            logger.info("  Pooling mode: %s", metadata.pooling_mode)
            if args.quantize:
                logger.info("  Quantization: INT8 (dynamic)")
        
        return 0
        
    except KeyboardInterrupt:
        logger.warning("Conversion interrupted by user")
        cleanup_on_failure(output_dir)
        return 130  # Standard exit code for SIGINT
        
    except Exception as e:
        logger.error("Model conversion failed: %s", e, exc_info=True)
        cleanup_on_failure(output_dir)
        return 1


if __name__ == "__main__":
    sys.exit(main())
