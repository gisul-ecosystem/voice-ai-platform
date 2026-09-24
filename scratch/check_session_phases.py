from pymongo import MongoClient
import sys

sys.path.insert(0, 'services/voice-agent')
from products.interviewer.policy import outline_from_definition
from products.interviewer.flow import extract_resume_projects

c = MongoClient('mongodb://localhost:27017/')
db = c['voiceai_pilot']
sess = db['interview_sessions'].find_one({'_id': 'ses_4b9dcd22adc84596861e52e370ec1ce6'})
defn = db['interview_definitions'].find_one({'_id': sess.get('definition_id')})
ctx = db['interview_contexts'].find_one({'_id': sess.get('context_id')})

resume_text = ctx.get('resume_text', '')
projects = extract_resume_projects(resume_text)
print('Extracted resume projects:', projects)

outline = outline_from_definition(defn, resume_projects=projects)
print('Phases in outline:')
for i, p in enumerate(outline.get('phases', [])):
    print(f"  [{i}] name={p.get('name')!r} intent={p.get('intent')!r} cid={p.get('competency_id')!r}")
