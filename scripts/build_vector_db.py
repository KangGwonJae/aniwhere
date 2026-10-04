from aniwhere.api.server import AGENT, DB_PATH

print(f"Built {DB_PATH}")
print(f"semantic chunks: {AGENT.store.count('semantic')}")
print(f"whole-document chunks: {AGENT.store.count('whole')}")
