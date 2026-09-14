#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import urllib.parse
import urllib.request
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signing_key(secret: str, short_date: str, region: str) -> bytes:
    date_key = hmac.new(("AWS4" + secret).encode(), short_date.encode(), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode(), hashlib.sha256).digest()
    service_key = hmac.new(region_key, b"s3", hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


def quote_path(value: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="-_.~") for part in value.split("/"))


def config(env: dict[str, str]) -> tuple[str, str, str, str, str]:
    access = env.get("TOS_ACCESS_KEY_ID") or env.get("VOLC_ACCESS_KEY_ID") or ""
    secret = env.get("TOS_SECRET_ACCESS_KEY") or env.get("VOLC_SECRET_ACCESS_KEY") or ""
    bucket = env.get("TOS_BUCKET", "")
    endpoint = env.get("TOS_ENDPOINT", "tos-s3-cn-beijing.volces.com")
    region = env.get("TOS_REGION") or env.get("VOLC_REGION") or "cn-beijing"
    if not all((access, secret, bucket)):
        raise RuntimeError("TOS credentials are incomplete")
    host = endpoint if endpoint.startswith(bucket + ".") else f"{bucket}.{endpoint}"
    return access, secret, bucket, region, host


def upload(path: Path, env: dict[str, str], object_key: str) -> dict[str, str]:
    access, secret, bucket, region, host = config(env)
    uri = "/" + quote_path(object_key)
    url = f"https://{host}{uri}"
    body = path.read_bytes()
    payload_hash = hashlib.sha256(body).hexdigest()
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")
    headers_text = f"content-type:{content_type}\nhost:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{timestamp}\n"
    signed_headers = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical = "\n".join(["PUT", uri, "", headers_text, signed_headers, payload_hash])
    scope = f"{short_date}/{region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", timestamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = hmac.new(signing_key(secret, short_date, region), to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = f"AWS4-HMAC-SHA256 Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    request = urllib.request.Request(url, data=body, method="PUT", headers={
        "Authorization": authorization,
        "Content-Type": content_type,
        "Host": host,
        "X-Amz-Content-Sha256": payload_hash,
        "X-Amz-Date": timestamp,
    })
    with urllib.request.urlopen(request, timeout=300) as response:
        if response.status >= 300:
            raise RuntimeError(f"TOS upload HTTP {response.status}")
    return {"bucket": bucket, "region": region, "host": host, "uri": uri, "object_key": object_key}


def presign_get(env: dict[str, str], host: str, uri: str, expires: int) -> str:
    access, secret, _, region, _ = config(env)
    now = dt.datetime.now(dt.timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")
    scope = f"{short_date}/{region}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access}/{scope}",
        "X-Amz-Date": timestamp,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    query = urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote, safe="-_.~")
    canonical = "\n".join(["GET", uri, query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", timestamp, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = hmac.new(signing_key(secret, short_date, region), to_sign.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}{uri}?{query}&X-Amz-Signature={signature}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload a video to configured TOS and create a temporary signed URL file.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--url-output", type=Path, required=True)
    parser.add_argument("--prefix", default="bai-video-shot-groups")
    parser.add_argument("--expires", type=int, default=21600)
    args = parser.parse_args()

    source = args.input.resolve()
    env = load_env(args.env_file.resolve())
    digest = sha256_file(source)
    manifest_path = args.manifest.resolve()
    existing = json.loads(manifest_path.read_text(encoding="utf-8-sig")) if manifest_path.exists() else {"objects": {}}
    saved = existing.setdefault("objects", {}).get(digest)
    reused = bool(saved and saved.get("host") and saved.get("uri"))
    if reused:
        metadata = saved
    else:
        object_key = f"{args.prefix.strip('/')}/{digest[:16]}/{source.name}"
        metadata = upload(source, env, object_key)
        metadata.update({"sha256": digest, "source_name": source.name, "size_bytes": source.stat().st_size})
        existing["objects"][digest] = metadata
        atomic_json(manifest_path, existing)

    signed_url = presign_get(env, metadata["host"], metadata["uri"], args.expires)
    check = urllib.request.Request(signed_url, method="GET", headers={"Range": "bytes=0-0"})
    with urllib.request.urlopen(check, timeout=60) as response:
        if response.status not in (200, 206):
            raise RuntimeError(f"Signed URL validation HTTP {response.status}")
    expiry = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=args.expires)
    atomic_json(args.url_output.resolve(), {"signed_url": signed_url, "expires_at": expiry.isoformat(), "sha256": digest})
    print(json.dumps({"status": "ready", "reused": reused, "object_key": metadata["object_key"], "size_bytes": metadata["size_bytes"], "url_output": str(args.url_output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
