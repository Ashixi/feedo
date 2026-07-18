import httpx
import zipfile
import io

CONSENSUS_NODE_URL = "http://localhost:3000"
STORAGE_NODE_URL = "http://localhost:3001"

try:
    res = httpx.get(f"{CONSENSUS_NODE_URL}/resolve/consensia.feedo")
    print("Consensus Response:", res.status_code, res.text)
    data = res.json()
    cid = data["cid"]
    print("CID:", cid)

    res2 = httpx.get(f"{STORAGE_NODE_URL}/download/{cid}")
    print("Storage Response:", res2.status_code, len(res2.content), "bytes")

    with zipfile.ZipFile(io.BytesIO(res2.content)) as zf:
        print("ZIP Contents:", zf.namelist())

except Exception as e:
    print("Error:", e)
