#!/bin/bash
#
# PHARMYRUS V18 - AUTOMATED DEPLOYMENT SCRIPT
# Deploy para Railway em 3 comandos
#

set -e  # Exit on error

echo "======================================================================"
echo "🚀 PHARMYRUS V18 - AUTOMATED DEPLOYMENT"
echo "======================================================================"

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo ""
    echo "⚠️  Railway CLI not found!"
    echo ""
    echo "Install Railway CLI:"
    echo "  npm i -g @railway/cli"
    echo ""
    echo "Or deploy manually via web:"
    echo "  https://railway.app/new"
    echo ""
    exit 1
fi

echo ""
echo "📋 Step 1/3: Railway Login"
echo "======================================================================"
railway login

echo ""
echo "📋 Step 2/3: Create New Project"
echo "======================================================================"
railway init

echo ""
echo "📋 Step 3/3: Deploy"
echo "======================================================================"
railway up

echo ""
echo "======================================================================"
echo "✅ DEPLOYMENT COMPLETE!"
echo "======================================================================"
echo ""
echo "🔗 Get your app URL:"
echo "   railway domain"
echo ""
echo "📊 View logs:"
echo "   railway logs"
echo ""
echo "🔍 Test your deployment:"
echo "   curl https://YOUR-APP.railway.app/health"
echo ""
echo "======================================================================"
