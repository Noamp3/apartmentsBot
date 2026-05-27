"""
Verify that the new sass generation prompt produces sexual and roasting responses.
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ai_engine import GeminiAIEngine


async def main():
    print("\n" + "="*60)
    print("🔥 TESTING NEW SASS GENERATION 🔥")
    print("="*60 + "\n")
    
    # Initialize AI engine without cache repo (for testing)
    ai_engine = GeminiAIEngine(cache_repo=None)
    
    print("📝 Generating a batch of sass lines...")
    print("This will create 30 new sexual/roasting sass lines.\n")
    
    try:
        # Generate sass batch
        await ai_engine._generate_sass_batch()
        
        print(f"\n✅ Generated {len(ai_engine._sass_cache)} sass lines!")
        print("\n" + "="*60)
        print("📋 SAMPLE SASS LINES (first 10):")
        print("="*60 + "\n")
        
        # Display first 10
        for i, sass in enumerate(ai_engine._sass_cache[:10], 1):
            print(f"{i:2d}. {sass}")
        
        if len(ai_engine._sass_cache) > 10:
            print(f"\n... and {len(ai_engine._sass_cache) - 10} more lines.\n")
        
        print("\n" + "="*60)
        print("🎯 TESTING parse_user_rules sass response:")
        print("="*60 + "\n")
        
        test_inputs = [
            "דירה בתל אביב עד 5000 שקל",
            "3 חדרים בפלורנטין",
            "ליד הים עם חניה"
        ]
        
        for test_text in test_inputs:
            print(f"📥 Input: \"{test_text}\"")
            rules, sass = await ai_engine.parse_user_rules(test_text)
            print(f"💅 Sass: {sass}")
            print(f"📋 Rules parsed: {len(rules)}")
            print()
        
        print("="*60)
        print("✅ VERIFICATION COMPLETE!")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
