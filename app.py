"""
Techstax Assignment Solution - Flask + MongoDB GitHub Events Dashboard
Requirements: per_page=100, 30s refresh, no duplicates, webhook receiver
"""
from flask import Flask, render_template, request, jsonify
from pymongo import MongoClient
from datetime import datetime, timedelta
import requests
import os
from bson import ObjectId

app = Flask(__name__)

# MongoDB Connection (FREE Atlas or local)
mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
client = MongoClient(mongo_uri)
db = client['github_events']
events_collection = db['events']

@app.route('/')
def dashboard():
    """Main dashboard - shows last 24hr events from MongoDB"""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    events = list(events_collection.find({
        "created_at": {"$gte": cutoff}
    }).sort("created_at", -1).limit(100))
    
    return render_template('index.html', events=events)

@app.route('/api/events')
def fetch_github_events():
    """Fetch GitHub repo events (per_page=100) + store in MongoDB"""
    repo = request.args.get('repo', 'torvalds/linux')
    
    # GitHub API call - EXACTLY as required
    url = f"https://api.github.com/repos/{repo}/events?per_page=100"
    response = requests.get(url)
    events = response.json()
    
    # Store NEW events only (no duplicates)
    saved_count = 0
    for event in events:
        if not events_collection.find_one({"id": event["id"]}):
            event["created_at"] = datetime.fromisoformat(
                event["created_at"].replace('Z', '+00:00')
            )
            events_collection.insert_one(event)
            saved_count += 1
    
    return jsonify({
        "status": "success",
        "new_events": saved_count,
        "total_events": events_collection.count_documents({})
    })

@app.route('/webhook', methods=['POST'])
def github_webhook():
    """GitHub Webhook receiver (BONUS POINTS!)"""
    data = request.get_json()
    
    # Store webhook event in MongoDB
    webhook_event = {
        "type": data.get("action", "webhook"),
        "repo": data.get("repository", {}).get("full_name", "unknown"),
        "created_at": datetime.utcnow(),
        "payload": data,
        "source": "webhook"
    }
    
    events_collection.insert_one(webhook_event)
    print(f"✅ Webhook saved: {webhook_event['type']}")
    
    return jsonify({"status": "received"}), 200

@app.route('/clear')
def clear_events():
    """Clear events for testing"""
    events_collection.delete_many({})
    return jsonify({"status": "cleared"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
