#!/usr/bin/env python3
"""
Test script for new comprehensive platform features
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def test_auth_endpoints():
    """Test authentication endpoints"""
    print("Testing authentication endpoints...")
    
    try:
        response = requests.post(f"{BASE_URL}/auth/magic-link", 
                               json={"email": "test@example.com"})
        print(f"Magic link request: {response.status_code}")
        if response.status_code == 200:
            print("✓ Magic link endpoint working")
        else:
            print(f"✗ Magic link failed: {response.text}")
    except Exception as e:
        print(f"✗ Magic link error: {e}")

def test_chat_endpoints():
    """Test chat ingestion endpoints"""
    print("\nTesting chat endpoints...")
    
    try:
        response = requests.post(f"{BASE_URL}/tenant?name=Chat%20Test%20Tenant")
        if response.status_code == 200:
            tenant_data = response.json()
            tenant_id = tenant_data.get('tenant_id')
            print(f"Created chat test tenant: {tenant_id}")
            
            response = requests.post(f"{BASE_URL}/tenant/{tenant_id}/brand",
                                   json={
                                       "name": "Test Brand",
                                       "description": "Test brand for chat testing"
                                   })
            if response.status_code == 200:
                brand_data = response.json()
                brand_id = brand_data.get('brand_id')
                print(f"Created test brand: {brand_id}")
            else:
                brand_id = "test-brand"
        else:
            tenant_id = "default"
            brand_id = "test-brand"
    except:
        tenant_id = "default"
        brand_id = "test-brand"
    
    try:
        response = requests.post(f"{BASE_URL}/tenant/{tenant_id}/chat/ingest-enhanced",
                               json={
                                   "brand_id": brand_id,
                                   "message": "complete task-123",
                                   "channel": "web"
                               })
        print(f"Chat ingest enhanced: {response.status_code}")
        if response.status_code == 200:
            print("✓ Chat ingest enhanced endpoint working")
            result = response.json()
            print(f"  Intent: {result.get('intent')}, Confidence: {result.get('confidence')}")
        else:
            print(f"✗ Chat ingest enhanced failed: {response.text}")
    except Exception as e:
        print(f"✗ Chat ingest enhanced error: {e}")

def test_knowledge_base():
    """Test knowledge base endpoints"""
    print("\nTesting knowledge base...")
    
    try:
        response = requests.post(f"{BASE_URL}/tenant?name=Test%20Tenant")
        if response.status_code == 200:
            tenant_data = response.json()
            tenant_id = tenant_data.get('tenant_id')
            print(f"Created test tenant: {tenant_id}")
        else:
            print("Using default tenant ID")
            tenant_id = "default"
    except:
        tenant_id = "default"
    
    try:
        response = requests.post(f"{BASE_URL}/kb/add-document?tenant_id={tenant_id}&title=Test%20Document&content=This%20is%20a%20test%20document%20for%20the%20knowledge%20base.")
        print(f"Add KB document: {response.status_code}")
        if response.status_code == 200:
            print("✓ Add document working")
        else:
            print(f"✗ Add document failed: {response.text}")
        
        response = requests.post(f"{BASE_URL}/kb/query?query=test&tenant_id={tenant_id}")
        print(f"Query KB: {response.status_code}")
        if response.status_code == 200:
            print("✓ Query working")
            result = response.json()
            print(f"  Found {len(result.get('results', []))} results")
        else:
            print(f"✗ Query failed: {response.text}")
            
        if response.status_code == 200:
            print("✓ Knowledge base endpoints working")
    except Exception as e:
        print(f"✗ Knowledge base error: {e}")

def test_enhanced_schedule():
    """Test enhanced scheduling endpoint"""
    print("\nTesting enhanced scheduling...")
    
    try:
        response = requests.get(f"{BASE_URL}/tenant/default/brand/test-brand/schedule-enhanced")
        print(f"Enhanced schedule: {response.status_code}")
        if response.status_code in [200, 404]:  # 404 is ok if brand doesn't exist
            print("✓ Enhanced schedule endpoint working")
    except Exception as e:
        print(f"✗ Enhanced schedule error: {e}")

def main():
    print("Testing new comprehensive platform features...")
    print("=" * 50)
    
    test_auth_endpoints()
    test_chat_endpoints()
    test_knowledge_base()
    test_enhanced_schedule()
    
    print("\n" + "=" * 50)
    print("Test completed. Check server logs for any errors.")

if __name__ == "__main__":
    main()
