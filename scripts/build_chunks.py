import json
from pathlib import Path

from aniwhere.chunking.service import semantic_chunks
from aniwhere.ingest.catalog import ROOT, load_anime

output = ROOT / "data" / "processed" / "chunks.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(semantic_chunks(load_anime()), ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Wrote {output}")
