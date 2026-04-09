from src.services.firestore_service import FirestoreService

def main():
    fs = FirestoreService()
    doc = next(fs.db.collection("Leads").limit(1).stream())
    print("DOC ID:", doc.id)
    print("DATA:", doc.to_dict())

if __name__ == "__main__":
    main()
