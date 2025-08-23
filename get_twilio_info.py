#!/usr/bin/env python3
"""
Get Twilio account information and available phone numbers using API
"""
from twilio.rest import Client
import os

account_sid = "AC0451fba473ccbf6dbc4f6b7e4666cc91"
auth_token = "612696e9d7cd577dce6d7688f27af1f7"

def get_twilio_account_info():
    """Get Twilio account information and phone numbers"""
    try:
        client = Client(account_sid, auth_token)
        
        account = client.api.accounts(account_sid).fetch()
        print(f"✅ Twilio Account Connected Successfully!")
        print(f"Account Name: {account.friendly_name}")
        print(f"Account Status: {account.status}")
        print(f"Account SID: {account.sid}")
        print()
        
        print("📱 Available Phone Numbers:")
        phone_numbers = client.incoming_phone_numbers.list()
        
        if not phone_numbers:
            print("❌ No phone numbers found in this account")
            print("You need to purchase a phone number from Twilio Console")
            return None
        
        whatsapp_numbers = []
        sms_numbers = []
        
        for number in phone_numbers:
            print(f"Number: {number.phone_number}")
            print(f"  Friendly Name: {number.friendly_name}")
            print(f"  Capabilities: Voice={number.capabilities['voice']}, SMS={number.capabilities['sms']}")
            
            if hasattr(number, 'capabilities') and 'whatsapp' in str(number.capabilities).lower():
                whatsapp_numbers.append(number.phone_number)
                print(f"  ✅ WhatsApp Enabled")
            elif number.capabilities['sms']:
                sms_numbers.append(number.phone_number)
                print(f"  📱 SMS Capable (can be used for WhatsApp)")
            
            print()
        
        print("🔧 WhatsApp Setup Recommendations:")
        if whatsapp_numbers:
            print(f"✅ Found {len(whatsapp_numbers)} WhatsApp-enabled numbers:")
            for num in whatsapp_numbers:
                print(f"  - {num}")
            print("Use any of these numbers for WHATSAPP_NUMBER in .env")
        elif sms_numbers:
            print(f"📱 Found {len(sms_numbers)} SMS-capable numbers that can be enabled for WhatsApp:")
            for num in sms_numbers:
                print(f"  - {num}")
            print("\n🚀 To enable WhatsApp on these numbers:")
            print("1. Go to Twilio Console → Phone Numbers → Manage → Active numbers")
            print("2. Click on a number")
            print("3. Enable WhatsApp in the Messaging section")
            print("4. Set webhook URL to: https://your-domain.com/webhooks/whatsapp")
        else:
            print("❌ No suitable numbers found. You need to:")
            print("1. Purchase a phone number from Twilio Console")
            print("2. Enable WhatsApp messaging on the number")
            print("3. Configure webhook URL")
        
        print("\n📍 US-based Number Recommendations:")
        print("✅ US numbers (+1) are recommended for:")
        print("  - Better deliverability in US/Canada")
        print("  - Lower costs for domestic messaging")
        print("  - Easier compliance with US regulations")
        print("  - WhatsApp Business API approval process")
        
        print("\n⚠️  Verification Requirements:")
        print("- WhatsApp Business numbers require Facebook Business verification")
        print("- This can take 1-3 business days for approval")
        print("- You'll need business documentation (website, business license, etc.)")
        print("- For testing, you can use SMS-capable numbers initially")
        
        if whatsapp_numbers:
            return whatsapp_numbers[0]
        elif sms_numbers:
            return sms_numbers[0]
        else:
            return None
            
    except Exception as e:
        print(f"❌ Error connecting to Twilio: {e}")
        return None

if __name__ == "__main__":
    recommended_number = get_twilio_account_info()
    if recommended_number:
        print(f"\n🎯 Recommended WHATSAPP_NUMBER for .env: {recommended_number}")
