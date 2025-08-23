#!/usr/bin/env python3
"""
Debug script to check which endpoints are registered with FastAPI
"""
import requests
import json

BASE_URL = "http://localhost:8000"

def check_openapi_spec():
    """Check OpenAPI spec to see registered endpoints"""
    try:
        response = requests.get(f"{BASE_URL}/openapi.json")
        if response.status_code == 200:
            spec = response.json()
            paths = spec.get('paths', {})
            print("Registered endpoints:")
            for path, methods in paths.items():
                for method in methods.keys():
                    print(f"  {method.upper()} {path}")
            
            kb_add = '/kb/add-document' in paths
            kb_query = '/kb/query' in paths
            chat_ingest = any('/chat/ingest-enhanced' in path for path in paths.keys())
            
            print(f"\nEndpoint status:")
            print(f"  /kb/add-document: {'✓' if kb_add else '✗'}")
            print(f"  /kb/query: {'✓' if kb_query else '✗'}")
            print(f"  /chat/ingest-enhanced: {'✓' if chat_ingest else '✗'}")
            
        else:
            print(f"Failed to get OpenAPI spec: {response.status_code}")
    except Exception as e:
        print(f"Error checking OpenAPI spec: {e}")

if __name__ == "__main__":
    check_openapi_spec()
