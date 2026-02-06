#!/usr/bin/env python3
"""
Generate runbook entries for IncidentIQ

Usage:
    python data/generate_runbooks.py
    python data/generate_runbooks.py --count 15
    python data/generate_runbooks.py --dry-run
"""

import argparse
import hashlib
import json
import os
from datetime import datetime
from typing import Dict, List

from dotenv import load_dotenv
from elasticsearch import Elasticsearch, helpers
from tqdm import tqdm

# Optional sentence transformer for embeddings
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_MODEL_AVAILABLE = True
except ImportError:
    print("⚠️ sentence_transformers not installed. Run `pip install sentence-transformers` for embeddings.")
    SENTENCE_MODEL_AVAILABLE = False

# Load environment variables
load_dotenv()

# Elasticsearch index
RUNBOOK_INDEX = "incidentiq-docs-runbooks"

# Runbook templates (simplified for brevity)
RUNBOOK_TEMPLATES = {
    "database_pool_exhaustion": {
        "service": "api-gateway",
        "title": "Fixing Database Connection Pool Exhaustion",
        "content": "Full documentation content...",
        "error_types": ["DatabaseTimeoutException", "ConnectionPoolExhaustedException", "SQLTimeoutException"],
        "resolution_procedures": ["Verify symptoms via logs and metrics", "Perform rolling service restart", "Monitor recovery metrics", "Increase pool size if needed"],
        "success_rate": 0.95,
        "tags": ["database", "connection_pool", "timeout", "restart", "api-gateway"]
    },
    "memory_leak_resolution": {
        "service": "notification-service",
        "title": "Memory Leak Detection and Resolution",
        "content": "Full documentation content...",
        "error_types": ["OutOfMemoryError", "GCOverheadLimitExceeded", "ContainerOOMKilled"],
        "resolution_procedures": ["Collect heap dump and diagnostics", "Attempt garbage collection", "Deploy memory leak hotfix", "Monitor memory stability"],
        "success_rate": 0.88,
        "tags": ["memory_leak", "oom", "java", "heap_dump", "deployment"]
    },
    # Add remaining templates here...
}

class RunbookGenerator:
    def __init__(self, es_client: Elasticsearch, count: int = 10):
        self.es = es_client
        self.count = count
        if SENTENCE_MODEL_AVAILABLE:
            print("🤖 Loading sentence transformer model for embeddings...")
            self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        else:
            self.embedding_model = None

    def generate_error_signature(self, service: str, error_type: str) -> str:
        """Generate consistent error signature hash"""
        signature_input = f"{service}:{error_type}"
        return hashlib.md5(signature_input.encode()).hexdigest()[:8]

    def generate_embedding(self, content: str) -> List[float]:
        """Generate embedding for runbook content (fallback to None if model unavailable)"""
        if self.embedding_model:
            return self.embedding_model.encode(content[:1000]).tolist()
        return None

    def select_runbooks_to_generate(self) -> List[tuple]:
        """Select runbooks based on requested count"""
        available = list(RUNBOOK_TEMPLATES.items())
        return available[:min(self.count, len(available))]

    def generate_runbook(self, runbook_id: str, template_name: str, template: Dict) -> Dict:
        """Generate single runbook document"""
        error_signatures = [self.generate_error_signature(template["service"], et) for et in template["error_types"]]
        embedding = self.generate_embedding(template["content"])
        
        doc = {
            "runbook_id": runbook_id,
            "service": template["service"],
            "title": template["title"],
            "content": template["content"],
            "error_signatures": error_signatures,
            "error_types": template["error_types"],
            "resolution_procedures": template["resolution_procedures"],
            "success_rate": template["success_rate"],
            "verified": True,
            "tags": template["tags"],
            "created_at": datetime.utcnow().isoformat() + "Z",
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "version": "1.0",
            "environment": "production"
        }
        
        # Add embedding only if available
        if embedding is not None:
            doc["content_embedding"] = embedding
        
        return doc

    def generate_runbooks(self, dry_run: bool = False) -> int:
        """Generate and insert runbooks"""
        runbooks = self.select_runbooks_to_generate()
        print(f"📚 Generating {len(runbooks)} runbook entries...")

        batch = []
        batch_size = 10
        with tqdm(total=len(runbooks), desc="Generating runbooks") as pbar:
            for i, (name, template) in enumerate(runbooks):
                runbook_id = f"RB-{i+1:03d}"
                doc = self.generate_runbook(runbook_id, name, template)

                if not dry_run:
                    batch.append({"_op_type": "create", "_index": RUNBOOK_INDEX, "_source": doc})

                # Preview first 3 runbooks
                if i < 3:
                    print(f"\n📖 Preview - {runbook_id}: {doc['service']} | {doc['title']} | Errors: {', '.join(doc['error_types'])}")

                if not dry_run and len(batch) >= batch_size:
                    try:
                        success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                        if errors:
                            print(f"\n⚠️  {len(errors)} runbooks failed to index")
                    except Exception as e:
                        print(f"\n⚠️  Bulk insert error: {e}")
                    batch = []

                pbar.update(1)

        if not dry_run and batch:
            try:
                success, errors = helpers.bulk(self.es, batch, raise_on_error=False)
                if errors:
                    print(f"\n⚠️  {len(errors)} runbooks in final batch failed to index")
                    if errors:
                        print(f"First error: {errors[0]}")
            except Exception as e:
                print(f"\n⚠️  Final bulk insert error: {e}")

        return len(runbooks)

def setup_elasticsearch() -> Elasticsearch:
    """Setup Elasticsearch connection"""
    es_config = {}
    if os.getenv("ELASTIC_CLOUD_ID"):
        es_config["cloud_id"] = os.getenv("ELASTIC_CLOUD_ID")
        if os.getenv("ELASTIC_API_KEY"):
            es_config["api_key"] = os.getenv("ELASTIC_API_KEY")
        elif os.getenv("ELASTIC_PASSWORD"):
            es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
    else:
        es_config["hosts"] = [os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")]
        if os.getenv("ELASTIC_PASSWORD"):
            es_config["basic_auth"] = ("elastic", os.getenv("ELASTIC_PASSWORD"))
    return Elasticsearch(**es_config)

def main():
    parser = argparse.ArgumentParser(description="Generate runbook entries for IncidentIQ")
    parser.add_argument("--count", type=int, default=10, help="Number of runbooks to generate")
    parser.add_argument("--dry-run", action="store_true", help="Preview without inserting data")
    args = parser.parse_args()

    print("📚 IncidentIQ Runbook Generator")
    print("=" * 50)

    try:
        es = setup_elasticsearch()
        es.info()
        print("✅ Connected to Elasticsearch")
    except Exception as e:
        print(f"❌ Elasticsearch connection failed: {e}")
        return 1

    generator = RunbookGenerator(es, count=args.count)
    start_time = datetime.utcnow()
    total_generated = generator.generate_runbooks(dry_run=args.dry_run)
    elapsed = datetime.utcnow() - start_time

    print("\n📈 Summary:")
    print(f"   • Total runbooks generated: {total_generated}")
    print(f"   • Execution time: {elapsed.total_seconds():.1f} seconds")
    if args.dry_run:
        print("   • Dry run mode - no data inserted")
    else:
        print(f"   • Runbooks inserted into index '{RUNBOOK_INDEX}'")

    return 0

if __name__ == "__main__":
    exit(main())
