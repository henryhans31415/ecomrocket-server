# External Services Setup Guide

This guide provides step-by-step instructions for configuring external services for the comprehensive multi-tenant platform.

## 🎯 Overview

The platform integrates with several external services:
- **Twilio**: WhatsApp/SMS messaging for chat ingestion
- **Postmark**: Transactional emails for magic link authentication
- **OpenAI**: NLP processing for chat intent parsing
- **Stripe**: Billing and subscription management (optional)

## 📋 Prerequisites

- Account credentials: henryhans31415@gmail.com / 904Transmissionhouse
- Access to service dashboards
- Platform already deployed and running

## 🔧 Service Configuration

### 1. Twilio Setup (WhatsApp/SMS)

**Step 1: Login to Twilio Console**
1. Go to https://console.twilio.com/
2. Login with henryhans31415@gmail.com / 904Transmissionhouse
3. Navigate to Account Dashboard

**Step 2: Get Credentials**
- **Account SID**: Found on main dashboard (starts with "AC")
- **Auth Token**: Click "Show" next to Auth Token on dashboard
- **WhatsApp Number**: Go to Phone Numbers → Manage → Active numbers

**Step 3: Configure Webhooks**
1. Go to Phone Numbers → Manage → Active numbers
2. Click on your WhatsApp-enabled number
3. Set webhook URL to: `https://your-domain.com/webhooks/whatsapp`
4. Set HTTP method to POST

### 2. Postmark Setup (Email)

**Step 1: Login to Postmark**
1. Go to https://account.postmarkapp.com/login
2. Login with henryhans31415@gmail.com / 904Transmissionhouse
3. Navigate to Servers

**Step 2: Get Server Token**
1. Select your server (or create new one)
2. Go to API Tokens tab
3. Copy the Server Token (starts with "xxxx-xxxx-xxxx")

**Step 3: Configure Sender Signature**
1. Go to Sender Signatures
2. Add and verify your sending domain/email
3. Set up DKIM records for better deliverability

### 3. OpenAI Setup (NLP)

**Step 1: Get API Key**
1. Go to https://platform.openai.com/api-keys
2. Login with your OpenAI account
3. Create new API key or use existing one

**Step 2: Set Usage Limits**
1. Go to Usage & Billing
2. Set appropriate monthly limits
3. Add payment method if needed

### 4. Stripe Setup (Billing) - Optional

**Step 1: Get API Keys**
1. Go to https://dashboard.stripe.com/apikeys
2. Get Publishable Key and Secret Key
3. Use test keys for development

**Step 2: Configure Webhooks**
1. Go to Developers → Webhooks
2. Add endpoint: `https://your-domain.com/webhooks/stripe`
3. Select relevant events (subscription updates, payments)

## 🚀 Automated Configuration

Use the provided configuration script:

```bash
cd /home/ubuntu/ecomrocket-server
python configure_external_services.py
```

This script will:
- Test all credentials
- Update .env file automatically
- Validate service connections
- Provide setup status

## 🧪 Testing

After configuration, test the services:

```bash
# Test all new features with real external services
python test_new_features.py

# Test specific endpoints
curl -X POST "http://localhost:8000/auth/magic-link" \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com"}'

# Test WhatsApp webhook (simulate Twilio callback)
curl -X POST "http://localhost:8000/webhooks/whatsapp" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "Body=test message&From=whatsapp:+1234567890"
```

## 🔒 Security Notes

- Never commit .env file with real credentials
- Use environment variables in production
- Rotate API keys regularly
- Set up proper webhook authentication
- Use HTTPS for all webhook endpoints

## 🐛 Troubleshooting

### Twilio Issues
- **Captcha problems**: Try incognito mode or different browser
- **Webhook not receiving**: Check URL is publicly accessible
- **WhatsApp not working**: Ensure number is WhatsApp-enabled

### Postmark Issues
- **Authentication failed**: Verify server token is correct
- **Emails not sending**: Check sender signature is verified
- **Bounces**: Set up proper SPF/DKIM records

### OpenAI Issues
- **Rate limits**: Check usage dashboard and limits
- **Invalid API key**: Regenerate key from dashboard
- **Model access**: Ensure you have access to required models

## 📞 Support

If you encounter issues:
1. Check service status pages
2. Review webhook logs in service dashboards
3. Test credentials with provided configuration script
4. Contact service support if needed

## 🎉 Success Criteria

Platform is fully configured when:
- ✅ All external service credentials are valid
- ✅ Webhook endpoints receive and process callbacks
- ✅ Magic link emails are delivered successfully
- ✅ WhatsApp messages are received and parsed
- ✅ Chat NLP processing works with real messages
- ✅ All comprehensive platform features are functional
