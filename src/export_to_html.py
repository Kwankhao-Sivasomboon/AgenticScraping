import os
import json
from google.cloud import firestore
from google.oauth2 import service_account
from dotenv import load_dotenv

load_dotenv()

def export_firestore_to_html():
    credentials_file = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json')
    try:
        cred = service_account.Credentials.from_service_account_file(credentials_file)
        db = firestore.Client(
            project=cred.project_id, 
            credentials=cred, 
            database='livinginsider-scraping'
        )
        
        print("[1/2] Fetching all documents from Firestore (Leads)...")
        docs = db.collection('Leads').stream()
        
        table_data = []
        for doc in docs:
            data = doc.to_dict()
            listing_id = doc.id
            
            # ดึงข้อมูลจาก sub-collection Analysis_Results
            analysis_doc = doc.reference.collection('Analysis_Results').document('evaluation').get()
            eval_data = analysis_doc.to_dict() if analysis_doc.exists else {}
            
            # รวมข้อมูลเข้าด้วยกัน
            row = {
                "ID": listing_id,
                "Project": eval_data.get("project_name", "-"),
                "Type": eval_data.get("type", "-"),
                "Price Sell": eval_data.get("price_sell", 0),
                "Price Rent": eval_data.get("price_rent", 0),
                "Phone": eval_data.get("phone_number", "-"),
                "Zone": data.get("zone", "-"),
                "Synced": "✅" if data.get("api_synced") else "⏳",
                "URL": data.get("url", "#")
            }
            table_data.append(row)
            
        print(f"[2/2] Generating HTML Table for {len(table_data)} records...")
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Firestore Leads Viewer</title>
            <link rel="stylesheet" type="text/css" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
            <style>
                body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background-color: #f4f7f6; }}
                h2 {{ color: #2c3e50; }}
                .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                table {{ width: 100%; }}
                .synced {{ color: green; font-weight: bold; }}
                .unsynced {{ color: orange; }}
                a {{ color: #3498db; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>📦 Firestore Leads Explorer ({len(table_data)} Total)</h2>
                <hr>
                <table id="leadsTable" class="display">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Project</th>
                            <th>Type</th>
                            <th>Price Sell</th>
                            <th>Price Rent</th>
                            <th>Phone</th>
                            <th>Zone</th>
                            <th>Status</th>
                            <th>Link</th>
                        </tr>
                    </thead>
                    <tbody>
        """
        
        for r in table_data:
            html_template += f"""
                <tr>
                    <td>{r['ID']}</td>
                    <td><b>{r['Project']}</b></td>
                    <td>{r['Type']}</td>
                    <td>{r['Price Sell']:,}</td>
                    <td>{r['Price Rent']:,}</td>
                    <td>{r['Phone']}</td>
                    <td>{r['Zone']}</td>
                    <td>{r['Synced']}</td>
                    <td><a href="{r['URL']}" target="_blank">Open Link</a></td>
                </tr>
            """
            
        html_template += """
                    </tbody>
                </table>
            </div>

            <script src="https://code.jquery.com/jquery-3.7.0.js"></script>
            <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
            <script>
                $(document).ready(function() {
                    $('#leadsTable').DataTable({
                        pageLength: 50,
                        order: [[0, 'desc']]
                    });
                });
            </script>
        </body>
        </html>
        """
        
        output_file = "view_leads.html"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(html_template)
            
        print(f"\n✨ เสร็จสิ้น! กรุณาเปิดไฟล์ '{os.path.abspath(output_file)}' ใน Browser เพื่อดูข้อมูลครับ")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    export_firestore_to_html()
