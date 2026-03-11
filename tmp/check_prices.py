import os
import sys
sys.path.append(os.getcwd())
from src.services.firestore_service import FirestoreService
import re

fs = FirestoreService()
# Leads is the collection name
docs = list(fs.db.collection('Leads').limit(10).stream())
print(f'--- RECENT LEADS (Total: {len(docs)}) ---')
for doc in docs:
    data = doc.to_dict()
    listing_id = doc.id
    
    # AI Analysis is in a sub-collection
    res = doc.reference.collection('Analysis_Results').document('evaluation').get()
    eval_data = res.to_dict() if res.exists else {}
    
    price_sell = eval_data.get('price_sell')
    price_rent = eval_data.get('price_rent')
    
    print(f'ID: {listing_id} | Sell: {price_sell} | Rent: {price_rent}')
