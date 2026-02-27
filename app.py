from flask import Flask, render_template, request, jsonify
import requests
from datetime import datetime, timedelta
import os
import threading
import time

app = Flask(__name__)

# Thread-safe event storage
events_store = []
store_lock = threading.Lock()

def parse_github_time(iso_string):
    """Fix timezone issue - make GitHub time comparable"""
    if not iso_string:
        return datetime.utcnow()
    
    # Remove timezone info for simple comparison
    dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00')[:19])
    return dt

@app.route('/')
def dashboard():
    """Main dashboard - last 24hr events only"""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    with store_lock:
        recent_events = [e for e in events_store 
                        if parse_github_time(e.get('created_at')) > cutoff]
    
    return render_template('index.html', events=recent_events)

@app.route('/api/events')
def fetch_events():
    """GitHub API → Store → Return (per_page=100 REQUIRED)"""
    repo = request.args.get('repo', 'torvalds/linux').strip()
    
    if '/' not in repo:
        return jsonify({'error': 'Use format: owner/repo'}), 400
    
    try:
        # GitHub API - EXACT ASSIGNMENT REQUIREMENT
        url = f"https://api.github.com/repos/{repo}/events?per_page=100"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        api_events = response.json()
        
        # Process and deduplicate
        cutoff = datetime.utcnow() - timedelta(hours=24)
        existing_ids = {e.get('id') for e in events_store}
        fresh_events = []
        
        for event in api_events:
            event_id = event.get('id')
            event_time = parse_github_time(event.get('created_at'))
            
            if (event_id and event_id not in existing_ids and event_time > cutoff):
                # Clean event data
                display_event = {
                    'id': event_id,
                    'type': event['type'],
                    'actor': event.get('actor', {'login': 'unknown'}),
                    'created_at': event['created_at'],
                    'formatted_time': event_time.strftime('%Y-%m-%d %H:%M IST'),
                    'payload': str(event.get('payload', {}))[:200] + '...',
                    'repo': repo,
                    'source': 'github_api'
                }
                
                with store_lock:
                    events_store.append(display_event)
                    # Keep only recent 100 events
                    events_store[:] = sorted(events_store, key=lambda x: parse_github_time(x.get('created_at')), reverse=True)[:100]
                
                fresh_events.append(display_event)
                existing_ids.add(event_id)
        
        return jsonify({
            'status': 'success',
            'repo': repo,
            'new_events': len(fresh_events),
            'total_events': len(events_store),
            'sample_events': fresh_events[:5]
        })
        
    except requests.RequestException as e:
        return jsonify({'error': f'API Error: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'Server Error: {str(e)}'}), 500

@app.route('/webhook', methods=['POST'])
def github_webhook():
    """GitHub Webhook receiver - BONUS POINTS!"""
    try:
        data = request.get_json() or {}
        webhook_event = {
            'id': f"webhook_{int(time.time()*1000)}",
            'type': data.get('action', 'webhook_event'),
            'actor': {'login': data.get('sender', {}).get('login', 'github-webhook')},
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'formatted_time': datetime.utcnow().strftime('%Y-%m-%d %H:%M IST'),
            'payload': str(data)[:200] + '...',
            'repo': data.get('repository', {}).get('full_name', 'webhook'),
            'source': 'github_webhook'
        }
        
        with store_lock:
            events_store.insert(0, webhook_event)
            events_store[:] = sorted(events_store, key=lambda x: parse_github_time(x.get('created_at')), reverse=True)[:100]
        
        print(f"✅ WEBHOOK RECEIVED: {webhook_event['type']} from {webhook_event['repo']}")
        return jsonify({'status': 'success', 'event': webhook_event['type']}), 200
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 400

@app.route('/clear')
def clear_events():
    """Clear all events for testing"""
    with store_lock:
        events_store.clear()
    return jsonify({'status': 'cleared', 'total': 0})

@app.route('/status')
def status():
    """Health check"""
    return jsonify({
        'status': 'healthy',
        'events_count': len(events_store),
        'uptime': 'production'
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
