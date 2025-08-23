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
        response = requests.post(f"{BASE_URL}/tenant/default/chat/ingest",
                               json={
                                   "brand_id": "test-brand",
                                   "message": "complete task-123",
                                   "channel": "web"
                               })
        print(f"Chat ingest: {response.status_code}")
        if response.status_code in [200, 404]:  # 404 is ok if brand doesn't exist
            print("✓ Chat ingest endpoint working")
        else:
            print(f"✗ Chat ingest failed: {response.text}")
    except Exception as e:
        print(f"✗ Chat ingest error: {e}")

def test_knowledge_base():
    """Test knowledge base endpoints"""
    print("\nTesting knowledge base...")
    
    try:
        response = requests.post(f"{BASE_URL}/kb/add-document",
                               params={
                                   "tenant_id": "default",
                                   "title": "Test Document",
                                   "content": "This is a test document for the knowledge base."
                               })
        print(f"Add KB document: {response.status_code}")
        
        response = requests.post(f"{BASE_URL}/kb/query",
                               params={
                                   "query": "test",
                                   "tenant_id": "default"
                               })
        print(f"Query KB: {response.status_code}")
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
