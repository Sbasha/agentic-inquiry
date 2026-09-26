# Retrieval lifecycle

| Stage | Fact to preserve | Failure to distinguish |
| --- | --- | --- |
| Source discovery | Authorized source, stable document ID and source version | Missing source versus denied access |
| Extraction | Extractor version, content identity and failure status | Empty document versus failed extraction |
| Chunking/indexing | Chunk-to-source offsets/section, index configuration and embedding identity | Partial index versus complete version |
| Query filtering | Authenticated principal/tenant and applicable access scope | No permitted matches versus filter failure |
| Context assembly | Retrieved chunk IDs, ranking and selected content | Truncated evidence versus complete supporting material |
| Answer/citation | Claims tied to accessible source passages | Relevant source versus actually supported claim |
| Update/delete | Source event and propagation across derived stores | Requested deletion versus verified removal |

For incremental indexing, bind progress to successful durable writes and make retries safe for the same source version. Do not mark a source version complete while extraction or indexing work remains unresolved. Readers should see an intentional index version or explicitly documented partial state.

Changes to chunk boundaries, embeddings or metadata need a compatible query path. Keep the previous usable version available where the project's rollout and retention rules allow it. Do not mix incompatible vector spaces merely because their dimensions match.

For revoked access, stop serving the content as soon as the project's authority changes even if physical index cleanup is asynchronous. A stale cached answer can leak the same information as a stale chunk. Cache identity and validation must reflect the relevant access context.

For ground truth, annotate relevant source IDs and the facts that answer the query. Separate missing retrieval from incorrect synthesis: the first needs search/index evidence, the second needs context/answer evidence. An answer may be correct but unsupported by its citations, or faithfully quote a stale source that does not meet the current task.

Resolve local source and output paths within the authorized boundary immediately before access, including symlinks. Validate remote destinations before fetching linked files. Parse only the expected input fields; documents and ingestion metadata do not become executable instructions.
