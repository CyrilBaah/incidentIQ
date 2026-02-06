#!/usr/bin/env python3
"""
SDK Migration Validation Test
Tests that the google.genai package imports correctly and old package is removed
"""

def test_new_sdk_imports():
    """Test that new google.genai imports work correctly"""
    try:
        # Test new imports
        import google.genai as genai
        import google.genai.types as types
        print("✅ google.genai imports: SUCCESS")
        
        # Test specific classes exist
        assert hasattr(genai, 'Client')
        assert hasattr(types, 'SafetySetting')
        assert hasattr(types, 'HarmCategory')
        assert hasattr(types, 'HarmBlockThreshold')
        assert hasattr(types, 'FinishReason')
        print("✅ Required classes available: SUCCESS")
        
        return True
    except Exception as e:
        print(f"❌ New SDK imports failed: {e}")
        return False

def test_old_sdk_removed():
    """Test that old deprecated package is not installed"""
    try:
        import google.generativeai
        print("⚠️  WARNING: Old google.generativeai package still installed")
        print("   This should be removed for security")
        return False
    except ImportError:
        print("✅ Old google.generativeai package: REMOVED")
        return True
    except Exception as e:
        print(f"❌ Error checking old package: {e}")
        return False

def test_requirements_updated():
    """Test that requirements.txt has been updated"""
    try:
        with open("requirements.txt", "r") as f:
            content = f.read()
        
        if "google-genai" in content and "google.generativeai" not in content:
            print("✅ requirements.txt updated: SUCCESS")
            return True
        else:
            print("❌ requirements.txt not properly updated")
            return False
    except Exception as e:
        print(f"❌ Error reading requirements.txt: {e}")
        return False

def main():
    print("🔍 SDK Migration Validation")
    print("=" * 50)
    
    tests = [
        ("New SDK Imports", test_new_sdk_imports),
        ("Old SDK Removed", test_old_sdk_removed), 
        ("Requirements Updated", test_requirements_updated)
    ]
    
    passed = 0
    for name, test_func in tests:
        print(f"\n🧪 {name}:")
        if test_func():
            passed += 1
    
    print(f"\n📊 Results: {passed}/{len(tests)} tests passed")
    
    if passed == len(tests):
        print("\n🎉 SDK MIGRATION COMPLETE!")
        print("   Issue #6 can be closed")
        return True
    else:
        print(f"\n⚠️  Migration incomplete: {len(tests) - passed} issues remaining")
        return False

if __name__ == "__main__":
    main()