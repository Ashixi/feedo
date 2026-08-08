import os
import httpx
import mimetypes
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, HTMLResponse

app = FastAPI(title="FEEDO Web2 Proxy Gateway")

CONSENSUS_NODE_URL = os.getenv("CONSENSUS_NODE_URL", "http://consensus-node:3000")
STORAGE_NODE_URL = os.getenv("STORAGE_NODE_URL", "http://storage-node:3001")

async def serve_landing_page():
    html = """
    <html>
        <head><title>FEEDO Web2 Proxy Gateway</title></head>
        <body style="font-family: sans-serif; text-align: center; margin-top: 50px;">
            <h1>FEEDO Web2 Proxy Gateway</h1>
            <p>Welcome to the gateway. To view a decentralized site, use a subdomain or path:</p>
            <p>Subdomain: <code>https://my-project.feedo.gateway.feedo.ink</code></p>
            <p>Path: <code>https://gateway.feedo.ink/my-project.feedo</code></p>
        </body>
    </html>
    """
    return HTMLResponse(html)

@app.get("/")
@app.get("/{domain_or_path:path}")
async def proxy_request(request: Request, domain_or_path: str = ""):
    host = request.headers.get("host", "")
    actual_domain = ""
    actual_path = ""

    # 1. Check for subdomain routing (e.g., consensia-feedo.gateway.feedo.ink)
    if ".gateway." in host:
        subdomain = host.split(".gateway.")[0]
        if subdomain.endswith("-feedo"):
            # Support hyphen instead of dot to bypass Let's Encrypt / Cloudflare wildcard limitations
            actual_domain = subdomain[:-6] + ".feedo"
            actual_path = domain_or_path
        elif subdomain.endswith(".feedo"):
            actual_domain = subdomain
            actual_path = domain_or_path
        else:
            if not domain_or_path:
                return await serve_landing_page()
            raise HTTPException(status_code=404, detail="Invalid FEEDO subdomain")
    else:
        # 2. Path routing (e.g., gateway.feedo.ink/consensia.feedo/...)
        if not domain_or_path or domain_or_path == "/":
            return await serve_landing_page()
            
        parts = domain_or_path.strip("/").split("/", 1)
        url_domain = parts[0]
        url_path = parts[1] if len(parts) > 1 else ""

        if url_domain.endswith(".feedo"):
            actual_domain = url_domain
            actual_path = url_path
        else:
            # Asset request with referer
            referer = request.headers.get("referer")
            if referer:
                from urllib.parse import urlparse
                parsed_referer = urlparse(referer)
                
                # Check if referer was using subdomain
                ref_host = parsed_referer.netloc
                if ".gateway." in ref_host:
                    ref_subdomain = ref_host.split(".gateway.")[0]
                    if ref_subdomain.endswith(".feedo"):
                        actual_domain = ref_subdomain
                        actual_path = domain_or_path
                    else:
                        raise HTTPException(status_code=404, detail="Invalid referer subdomain")
                else:
                    # Referer was using path
                    ref_parts = parsed_referer.path.strip("/").split("/")
                    if ref_parts and ref_parts[0].endswith(".feedo"):
                        actual_domain = ref_parts[0]
                        actual_path = domain_or_path
                    else:
                        raise HTTPException(status_code=404, detail="Invalid domain and unable to infer from referer")
            else:
                raise HTTPException(status_code=404, detail="Invalid domain (must end with .feedo)")

    if not actual_path or actual_path == "/":
        actual_path = "index.html"

    # --- Resolution and Fetching ---
    
    # Resolve domain
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(f"{CONSENSUS_NODE_URL}/resolve/{actual_domain}")
            if res.status_code != 200:
                raise HTTPException(status_code=404, detail="Domain not found in FEEDO network")
            data = res.json()
            if not data or not data.get("cid"):
                raise HTTPException(status_code=404, detail="Domain found but no content attached")
            cid = data["cid"]
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to connect to consensus node: {str(e)}")

    # Fetch content (ZIP archive)
    async with httpx.AsyncClient() as client:
        try:
            file_res = await client.get(f"{STORAGE_NODE_URL}/download/{cid}")
            if file_res.status_code != 200:
                raise HTTPException(status_code=404, detail="Content not found in DHT")
            zip_content = file_res.content
        except httpx.RequestError as e:
            raise HTTPException(status_code=500, detail=f"Failed to connect to storage node: {str(e)}")

    # Extract requested file from ZIP in memory
    import zipfile
    import io

    try:
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            file_names = zf.namelist()
            target_file = actual_path
            
            if target_file not in file_names:
                for name in file_names:
                    if name.endswith(f"/{actual_path}") or name == actual_path:
                        target_file = name
                        break
            
            if target_file not in file_names:
                # SPA Fallback: If the file doesn't have an extension, it's likely a client-side route
                # like /app or /dashboard. We should return index.html instead of 404.
                if "." not in actual_path.split("/")[-1] and actual_path != "":
                    fallback_file = "index.html"
                    for name in file_names:
                        if name.endswith("/index.html") or name == "index.html":
                            fallback_file = name
                            break
                    if fallback_file in file_names:
                        target_file = fallback_file
                    else:
                        raise HTTPException(status_code=404, detail=f"File '{actual_path}' not found in deployed archive.")
                else:
                    raise HTTPException(status_code=404, detail=f"File '{actual_path}' not found in deployed archive.")
                
            content = zf.read(target_file)
    except zipfile.BadZipFile:
        if actual_path == "index.html" or actual_path == "":
            content = zip_content
        else:
            raise HTTPException(status_code=400, detail="Deployment is not a valid ZIP archive")

    # Guess Mime Type
    mime_type, _ = mimetypes.guess_type(actual_path)
    if not mime_type:
        mime_type = "application/octet-stream"
    if "." not in actual_path.split("/")[-1]:
        mime_type = "text/html"

    # Set cache headers
    headers = {}
    if mime_type == "text/html":
        headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    else:
        # Assets with hashes can be cached, others should be verified
        headers["Cache-Control"] = "public, max-age=31536000, immutable"

    return Response(content=content, media_type=mime_type, headers=headers)
