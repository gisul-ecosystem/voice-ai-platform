import urllib.request
import json
import urllib.error

req = urllib.request.Request(
    'http://127.0.0.1:5554/interview-brain/jd/extract',
    data=b'{"job_description":"test","target_level":"junior"}',
    headers={'Authorization': 'Bearer local-dev-token', 'Content-Type': 'application/json'}
)

try:
    with urllib.request.urlopen(req) as response:
        print("Success:", response.read())
except urllib.error.HTTPError as e:
    print("Error:", e.code, e.reason, e.read())
