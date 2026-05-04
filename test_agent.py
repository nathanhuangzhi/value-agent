from app.workflow import run_discovery_workflow

if __name__ == "__main__":
    result = run_discovery_workflow()
    print("\n=== FINAL OUTPUT ===\n")
    print(result)
