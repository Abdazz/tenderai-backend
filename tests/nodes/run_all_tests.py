"""Run all node tests in sequence."""

import sys
import subprocess
from pathlib import Path

# ANSI color codes
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'
BOLD = '\033[1m'

# Test files to run
TESTS = [
    {
        'file': 'test_extraction.py',
        'name': 'Extraction Node',
        'description': 'Tests structured tender extraction from text'
    },
    {
        'file': 'test_classify.py',
        'name': 'Classification Node',
        'description': 'Tests keyword and LLM-based classification'
    },
    {
        'file': 'test_summarize.py',
        'name': 'Summarization Node',
        'description': 'Tests French summary generation'
    },
    {
        'file': 'test_deduplicate.py',
        'name': 'Deduplication Node',
        'description': 'Tests duplicate detection with LLM'
    }
]

def run_test(test_file):
    """Run a single test file."""
    test_path = Path(__file__).parent / test_file
    
    if not test_path.exists():
        print(f"{RED}  ❌ File not found: {test_file}{RESET}")
        return False
    
    try:
        result = subprocess.run(
            [sys.executable, str(test_path)],
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        # Print output
        if result.stdout:
            print(result.stdout)
        
        if result.stderr and result.returncode != 0:
            print(f"{RED}STDERR:{RESET}")
            print(result.stderr)
        
        return result.returncode == 0
        
    except subprocess.TimeoutExpired:
        print(f"{RED}  ❌ Test timed out (>60s){RESET}")
        return False
    except Exception as e:
        print(f"{RED}  ❌ Error: {e}{RESET}")
        return False

def main():
    """Run all tests and report results."""
    
    print(f"\n{BOLD}{BLUE}{'=' * 80}{RESET}")
    print(f"{BOLD}{BLUE}🧪 RFP Watch AI - Node Test Suite{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}\n")
    
    results = []
    
    for idx, test in enumerate(TESTS, 1):
        print(f"{BOLD}[{idx}/{len(TESTS)}] Testing: {test['name']}{RESET}")
        print(f"{YELLOW}  {test['description']}{RESET}")
        print(f"  File: {test['file']}\n")
        
        success = run_test(test['file'])
        results.append({
            'name': test['name'],
            'file': test['file'],
            'success': success
        })
        
        if success:
            print(f"\n{GREEN}  ✅ {test['name']} - PASSED{RESET}")
        else:
            print(f"\n{RED}  ❌ {test['name']} - FAILED{RESET}")
        
        print(f"\n{'-' * 80}\n")
    
    # Summary
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}")
    print(f"{BOLD}{BLUE}TEST SUMMARY{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 80}{RESET}\n")
    
    total = len(results)
    passed = sum(1 for r in results if r['success'])
    failed = total - passed
    
    print(f"Total tests: {total}")
    print(f"{GREEN}Passed: {passed}{RESET}")
    if failed > 0:
        print(f"{RED}Failed: {failed}{RESET}")
    
    print("\nDetailed Results:")
    for result in results:
        status = f"{GREEN}✅ PASS{RESET}" if result['success'] else f"{RED}❌ FAIL{RESET}"
        print(f"  {status} - {result['name']}")
    
    print(f"\n{BOLD}{BLUE}{'=' * 80}{RESET}\n")
    
    # Exit code
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    main()
