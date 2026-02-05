# #!/usr/bin/env python3
# """Test all service connections"""

# import os
# import sys
# from dotenv import load_dotenv

# # Load environment variables
# load_dotenv()

# def test_elasticsearch():
#     """Test Elasticsearch connection"""
#     print("\n🔍 Testing Elasticsearch connection...")
#     try:
#         from elasticsearch import Elasticsearch
        
#         cloud_id = os.getenv("ELASTIC_CLOUD_ID")
#         api_key = os.getenv("ELASTIC_API_KEY")
        
#         if not cloud_id or not api_key:
#             print("❌ ELASTIC_CLOUD_ID or ELASTIC_API_KEY not set in .env")
#             return False
        
#         es = Elasticsearch(
#             cloud_id=cloud_id,
#             api_key=api_key
#         )
        
#         # Test connection
#         info = es.info()
#         print(f"✅ Connected to Elasticsearch cluster: {info['cluster_name']}")
#         print(f"   Version: {info['version']['number']}")
        
#         # Test ES|QL
#         result = es.esql.query(query="FROM .kibana | LIMIT 1")
#         print("✅ ES|QL queries working!")
        
#         return True
        
#     except Exception as e:
#         print(f"❌ Elasticsearch connection failed: {e}")
#         return False

# def test_anthropic():
#     """Test Anthropic API connection"""
#     print("\n🤖 Testing Anthropic API connection...")
#     try:
#         import anthropic
        
#         api_key = os.getenv("ANTHROPIC_API_KEY")
        
#         if not api_key:
#             print("❌ ANTHROPIC_API_KEY not set in .env")
#             return False
        
#         client = anthropic.Anthropic(api_key=api_key)
        
#         # Test with a simple message
#         message = client.messages.create(
#             model="claude-sonnet-4-20250514",
#             max_tokens=100,
#             messages=[
#                 {"role": "user", "content": "Say 'Connection test successful!' and nothing else."}
#             ]
#         )
        
#         response = message.content[0].text
#         print(f"✅ Anthropic API connected!")
#         print(f"   Response: {response}")
        
#         return True
        
#     except Exception as e:
#         # Check if it's a credit balance issue (which means connection is working)
#         if "credit balance is too low" in str(e):
#             print(f"✅ Anthropic API connected! (Free tier - add credits for API calls)")
#             return True
#         else:
#             print(f"❌ Anthropic API connection failed: {e}")
#             return False

# def main():
#     """Run all tests"""
#     print("="*60)
#     print("IncidentIQ - Connection Tests")
#     print("="*60)
    
#     results = {
#         "Elasticsearch": test_elasticsearch(),
#         "Anthropic API": test_anthropic(),
#     }
    
#     print("\n" + "="*60)
#     print("RESULTS:")
#     print("="*60)
    
#     all_passed = True
#     for service, passed in results.items():
#         status = "✅ PASS" if passed else "❌ FAIL"
#         print(f"{service:20s} {status}")
#         if not passed:
#             all_passed = False
    
#     print("="*60)
    
#     if all_passed:
#         print("\n🎉 All connections successful! Ready to build IncidentIQ!")
#         return 0
#     else:
#         print("\n⚠️ Some connections failed. Check your .env file and credentials.")
#         return 1

# if __name__ == "__main__":
#     sys.exit(main())

#!/usr/bin/env python3
"""Test all service connections with Gemini support"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_elasticsearch():
    """Test Elasticsearch connection"""
    print("\n🔍 Testing Elasticsearch connection...")
    try:
        from elasticsearch import Elasticsearch
        
        cloud_id = os.getenv("ELASTIC_CLOUD_ID")
        api_key = os.getenv("ELASTIC_API_KEY")
        
        if not cloud_id or not api_key:
            print("❌ ELASTIC_CLOUD_ID or ELASTIC_API_KEY not set in .env")
            return False
        
        es = Elasticsearch(
            cloud_id=cloud_id,
            api_key=api_key
        )
        
        # Test connection
        info = es.info()
        print(f"✅ Connected to Elasticsearch cluster: {info['cluster_name']}")
        print(f"   Version: {info['version']['number']}")
        
        # Test ES|QL
        result = es.esql.query(query="FROM .kibana | LIMIT 1")
        print("✅ ES|QL queries working!")
        
        return True
        
    except Exception as e:
        print(f"❌ Elasticsearch connection failed: {e}")
        return False


def test_gemini():
    """Test Google Gemini API connection"""
    print("\n🤖 Testing Google Gemini API connection...")
    try:
        import google.generativeai as genai
        
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("❌ GOOGLE_API_KEY not set in .env")
            return False
        
        # Configure the API
        genai.configure(api_key=api_key)
        
        # Try the latest working models (based on API response)
        models_to_try = [
            "gemini-2.5-flash",
            "gemini-2.0-flash", 
            "gemini-flash-latest",
            "gemini-pro-latest"
        ]
        
        for model_name in models_to_try:
            try:
                print(f"   Trying model: {model_name}")
                model = genai.GenerativeModel(model_name)
                
                response = model.generate_content(
                    "Say 'Connection test successful!' and nothing else.",
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=50,
                        temperature=0.1,
                    )
                )
                
                response_text = response.text.strip()
                print(f"✅ Gemini API connected!")
                print(f"   Model: {model_name}")
                print(f"   Response: {response_text}")
                return True
                
            except Exception as model_error:
                print(f"   {model_name}: {str(model_error)[:80]}...")
                continue
        
        print("❌ No working Gemini models found")
        return False
        
    except Exception as e:
        print(f"❌ Gemini API connection failed: {e}")
        print("   Troubleshooting steps:")
        print("   1. Enable the Generative Language API: https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com")
        print("   2. Check your API key is valid")
        print("   3. Ensure you have proper billing/quota setup")
        return False


def test_anthropic():
    """Test Anthropic API connection (optional backup)"""
    print("\n🔷 Testing Anthropic API connection...")
    try:
        from anthropic import Anthropic
        
        api_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not api_key:
            print("⚠️  ANTHROPIC_API_KEY not set in .env")
            return None  # None means "not tested, but OK"
        
        client = Anthropic(api_key=api_key)
        
        # Test with a simple message
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=100,
            messages=[
                {"role": "user", "content": "Say 'Connection test successful!' and nothing else."}
            ]
        )
        
        response = message.content[0].text
        print(f"✅ Anthropic API connected!")
        print(f"   Model: claude-3-5-sonnet-20241022")
        print(f"   Response: {response}")
        
        return True
        
    except Exception as e:
        # Check if it's a credit balance issue (which means connection is working)
        if "credit balance is too low" in str(e):
            print(f"✅ Anthropic API connected! (Free tier - add credits for API calls)")
            return True
        else:
            print(f"⚠️  Anthropic API not available: {e}")
            return None


def main():
    """Run all tests"""
    print("="*60)
    print("IncidentIQ - Connection Tests")
    print("="*60)
    
    results = {
        "Elasticsearch": test_elasticsearch(),
        "Google Gemini": test_gemini(),
        "Anthropic": test_anthropic(),
    }
    
    print("\n" + "="*60)
    print("RESULTS:")
    print("="*60)
    
    # Check if at least one AI provider is working
    ai_providers_working = []
    all_required_passed = True
    
    for service, passed in results.items():
        if passed is None:
            status = "⚠️  SKIP (optional)"
        elif passed:
            status = "✅ PASS"
            if service in ["Google Gemini", "Anthropic"]:
                ai_providers_working.append(service)
        else:
            status = "❌ FAIL"
            if service == "Elasticsearch":  # Elasticsearch is required
                all_required_passed = False
        print(f"{service:25s} {status}")
    
    print("="*60)
    
    # Check if we have at least Elasticsearch + one AI provider
    has_ai_provider = len(ai_providers_working) > 0
    
    if all_required_passed and has_ai_provider:
        print(f"\n🎉 Core connections successful! Ready to build IncidentIQ!")
        if "Anthropic" in ai_providers_working:
            print("   💫 Using Anthropic Claude for AI features")
        if "Google Gemini" in ai_providers_working:
            print("   🤖 Using Google Gemini for AI features")
        print("\n💡 TIP: Both providers work well for incident management!")
        return 0
    elif all_required_passed:
        print(f"\n⚠️ Elasticsearch working but no AI provider available.")
        print("   Please fix either Gemini or Anthropic API configuration.")
        return 1
    else:
        print("\n⚠️ Some required connections failed. Check your .env file and credentials.")
        return 1


if __name__ == "__main__":
    sys.exit(main())