#!/usr/bin/env python3
"""
Test V18 Ultra-Resilient Crawler locally
"""
import asyncio
from ultra_resilient_crawler import UltraResilientCrawler


async def test_extraction_patterns():
    """Test pattern extraction without network"""
    print("\n" + "="*70)
    print("TEST 1: PATTERN EXTRACTION")
    print("="*70)
    
    # Mock proxies
    proxies = ["http://test:test@proxy1:8080"]
    crawler = UltraResilientCrawler(proxies)
    
    # Test HTML samples
    test_html = """
    <a href="/patent/WO2011051540A1">WO2011051540A1</a>
    Publication: WO 2016/162604 A1
    WO2018162793
    patent_id=WO2021229145
    <span>BR112012027681</span>
    BR 112017024082 A2
    /patent/BR112018012345
    """
    
    # Extract WO
    wo_numbers = crawler._extract_wo_numbers(test_html)
    print(f"\n✅ WO Extraction: {len(wo_numbers)} numbers")
    for wo in sorted(wo_numbers):
        print(f"   - {wo}")
    
    # Extract BR
    br_numbers = crawler._extract_br_numbers(test_html)
    print(f"\n✅ BR Extraction: {len(br_numbers)} numbers")
    for br in sorted(br_numbers):
        print(f"   - {br}")
    
    return len(wo_numbers) >= 3 and len(br_numbers) >= 2


async def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("PHARMYRUS V18 - LOCAL TESTING")
    print("="*70)
    
    # Test 1: Pattern extraction
    success = await test_extraction_patterns()
    
    if success:
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\n🚀 System ready for deployment!")
        print("\nNext steps:")
        print("1. git init && git add . && git commit -m 'V18 Ultra-Resilient'")
        print("2. git push to GitHub")
        print("3. Deploy to Railway")
        return 0
    else:
        print("\n❌ TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
