#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video.lucy.run ComfyUI Workbench 完整链路 CLI（登录 → 报价 → 提交 → 轮询 → 下载校验）。

全部端点均为 2026-10 实测验证。计价规则：100 units/秒（5s=500, 10s=1000, 15s=1500）。

用法:
  # 1) 微信扫码登录（需要 HMAC 密钥：环境变量 CEPHALON_PUBLIC_KEY/CEPHALON_PRIVATE_KEY
  #    或本地 cephalon_keys_local.py，见 cephalon_keys.py 模板说明）
  python lucy_run.py login
  export LUCY_UC_TOKEN=<上一步保存的 JWT>   # 或用 --token-file

  # 2) 日常操作
  python lucy_run.py balance                       # 查余额（user-center，Bearer）
  python lucy_run.py templates                     # 列出模板与参数
  python lucy_run.py upload 图片.png               # 上传素材 → asset_id（i2v/fl2v/r2v 用）
  python lucy_run.py quote --template t2v --seconds 5 --prompt "..."     # 零消耗报价
  python lucy_run.py submit --template t2v --seconds 5 --prompt "..." --yes
  python lucy_run.py submit --template i2v --seconds 5 --prompt "..." \
         --image first_frame=<asset_id> --yes
  python lucy_run.py status <run_id>
  python lucy_run.py download <run_id>             # 下载产物并 sha256 校验
  python lucy_run.py cancel <run_id>               # 仅 queued 态可取消（running 409）

安全须知:
  * ⚠️ 实验性：微信扫码登录链路为非官方逆向实现，可能违反平台服务条款，
    由此产生的账号风险（限流/封禁）由使用者自担。
  * submit 会真实扣费。扣费发生在提交瞬间，任务秒级进入 running，不可取消。
  * 提交前自动做零消耗 rehearsal 报价并展示价格，需 --yes 或交互确认。
  * Idempotency-Key 落盘后复用：网络重试不会重复扣费。
  * 凭据只从环境变量/本地文件读取，任何输出都会掩码，不落日志。

状态文件（--workdir，默认 ./lucy_state）:
  token.txt      user-center JWT（24h 有效）
  session.json   lucy Workbench 会话 cookie
  runs/<id>.json 每次提交的幂等键与参数（防孤儿/防重复扣费）
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Tuple

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/151.0.0.0 Safari/537.36")
UC = "https://prod.unicorn.org.cn/cephalon/user-center"
LUCY = "https://video.lucy.run"
SSO_BODY = {"app_id": "comfyui_platform", "redirect_uri": LUCY + "/auth/callback"}

# 模板别名 → 名称关键词（/api/workbench 返回的 name 含这些词）
ALIAS = {"t2v": "文生", "i2v": "图生", "fl2v": "首尾", "r2v": "参考"}
CT_BY_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp"}
PRICE_PER_SECOND = 100  # units，实测
FORBIDDEN = {("15", "544"): "15 秒只能配 resolution=480（960p 高度），544（1080p 高度）仅支持 5/10 秒"}


def mask(s):
    s = str(s or "")
    return s[:6] + "…" if len(s) > 10 else "…"


def warn(*a):
    print(*a, file=sys.stderr)


class Api:
    """Workbench（cookie 会话）+ user-center（Bearer/HMAC）双通道。"""

    def __init__(self, workdir, token):
        self.workdir = workdir
        self.token = token
        self.cookie = ""
        self.session_file = os.path.join(workdir, "session.json")
        if os.path.exists(self.session_file):
            self.cookie = self._load_cookie()

    # ---------- 底层 ----------
    def _workbench(self, url, data=None, method="GET", extra=None, timeout=60,
                   binary_out=None) -> Tuple[int, Any]:
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Cookie": self.cookie, "User-Agent": UA,
                   "Origin": LUCY, "Referer": LUCY + "/"}   # 无 Origin/Referer 必 403
        if extra:
            headers.update(extra)
        if body:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if binary_out:
                    b = resp.read()
                    with open(binary_out, "wb") as f:
                        f.write(b)
                    return resp.status, len(b)
                raw = resp.read().decode(errors="replace")
                try:
                    return resp.status, json.loads(raw)
                except ValueError:
                    return resp.status, raw[:400]
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")[:400]

    def _uc(self, path, data=None, method="GET", query="", timeout=30) -> Tuple[int, Any]:
        """user-center 请求（Bearer）。HMAC 端点（登录/二维码）直接用 cephalon_api.request。"""
        url = UC + path + query
        headers = {"Authorization": "Bearer " + self.token, "User-Agent": UA}
        body = json.dumps(data).encode() if data is not None else None
        if body:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode(errors="replace"))
            except Exception:
                return e.code, {}
        except Exception as e:
            return -1, {"msg": str(e)}

    def _load_cookie(self):
        with open(self.session_file) as f:
            s = json.load(f)
        return "; ".join(f"{k}={v}" for k, v in s.get("cookies", {}).items())

    # ---------- 会话 ----------
    def ensure_session(self, force=False):
        """无有效会话时用 Bearer JWT 走 SSO 换票建立 lucy cookie。"""
        if self.cookie and not force:
            st, _ = self._workbench(LUCY + "/api/workbench")
            if st == 200:
                return
            warn("会话失效，重新 SSO…")
        st, body = self._uc("/v1/platform/sso/tickets", data=SSO_BODY, method="POST")
        redirect_url = None
        if isinstance(body, dict):
            redirect_url = body.get("redirect_url") or (body.get("data") or {}).get("redirect_url")
        if st != 200 or not redirect_url:
            raise SystemExit(f"SSO 换票失败: {st} {json.dumps(body, ensure_ascii=False)[:200]}\n"
                             "JWT 过期？重新运行: python lucy_run.py login")
        import http.cookiejar
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(redirect_url, headers={"User-Agent": UA})
        opener.open(req, timeout=60).read()
        cookies = {c.name: c.value for c in cj}
        if not cookies:
            raise SystemExit("SSO 回调未取得 cookie，登录态异常")
        with open(self.session_file, "w") as f:
            json.dump({"cookies": cookies, "final_url": redirect_url}, f)
        self.cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        warn(f"会话已建立: {', '.join(k + '=' + mask(v) for k, v in cookies.items())}")

    # ---------- 高层操作 ----------
    def balance(self):
        st, body = self._uc("/v1/user/balance", query="?symbol_ids=1")
        if st != 200:
            raise SystemExit(f"余额查询失败: {st} {json.dumps(body, ensure_ascii=False)[:200]}")
        units = (body.get("data", {}).get("balances", {}) or {}).get("1")
        return units

    def templates(self):
        st, tpls = self._workbench(LUCY + "/api/workbench")
        if st != 200:
            raise SystemExit(f"模板列表失败: {st} {str(tpls)[:200]}")
        return tpls

    def resolve_template(self, tpls, key):
        key = key.strip()
        for t in tpls:
            if t["id"] == key:
                return t
        kw = ALIAS.get(key.lower())
        if kw:
            for t in tpls:
                if kw in t.get("name", ""):
                    return t
        raise SystemExit(f"找不到模板 {key}。可用: " +
                         ", ".join(f"{t['id'][:8]}({t['name']})" for t in tpls))

    def quote(self, template_id, values):
        return self._workbench(f"{LUCY}/api/workbench/{template_id}/quote",
                               data={"values": values, "purpose": "rehearsal"},
                               method="POST")

    def upload_asset(self, path):
        ext = os.path.splitext(path)[1].lower()
        ct = CT_BY_EXT.get(ext)
        if not ct:
            raise SystemExit(f"不支持的图片格式 {ext}，支持: {', '.join(CT_BY_EXT)}")
        data = open(path, "rb").read()
        st, up = self._workbench(LUCY + "/api/assets/uploads", method="POST",
                                 data={"filename": os.path.basename(path),
                                       "content_type": ct, "size": len(data)})
        if st not in (200, 201):
            raise SystemExit(f"创建上传失败: {st} {str(up)[:200]}")
        preq = urllib.request.Request(up["upload_url"], data=data, method="PUT",
                                      headers=up.get("headers") or {"Content-Type": ct})
        with urllib.request.urlopen(preq, timeout=300) as resp:
            if resp.status != 200:
                raise SystemExit(f"S3 上传失败: {resp.status}")
        st, comp = self._workbench(f"{LUCY}/api/assets/{up['asset_id']}/complete",
                                   method="POST", data={})
        if st != 200:
            raise SystemExit(f"complete 失败: {st} {str(comp)[:200]}")
        return up["asset_id"]

    def submit(self, template_id, values, assume_yes=False, wait=0, poll_gap=12):
        # 1) 提交前强制零消耗报价（防手滑扣费）
        st, q = self.quote(template_id, values)
        if st != 200:
            raise SystemExit(f"报价失败: {st} {json.dumps(q, ensure_ascii=False)[:300]}")
        amount, revision = q["amount"], q["revision"]
        spec = q.get("spec", {})
        seconds = values.get("seconds", 5)
        expect = PRICE_PER_SECOND * seconds
        if amount != expect:
            warn(f"注意: 服务端报价 {amount} ≠ 按时长估算 {expect}（{seconds}s），以服务端为准")
        print(f"报价: {amount} units = {amount / 100:.2f} CEP | spec "
              f"{spec.get('width')}x{spec.get('height')} f{spec.get('frames')} | revision {revision}")
        if not assume_yes:
            if not sys.stdin.isatty():
                raise SystemExit("非交互环境需 --yes 才会真实提交")
            if input(f"将真实扣费 {amount / 100:.2f} CEP，继续? [y/N] ").strip().lower() != "y":
                raise SystemExit("已取消")

        # 2) 幂等键：同参数重试复用，防重复扣费（先落盘再请求）
        values_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        pending = os.path.join(self.workdir, "runs", f"pending-{values_hash}.json")
        if os.path.exists(pending):
            with open(pending) as f:
                idem = json.load(f)["idem"]
            warn(f"复用已存在的幂等键 {idem[:8]}…（此前提交可能未确认）")
        else:
            idem = str(uuid.uuid4())
            os.makedirs(os.path.dirname(pending), exist_ok=True)
            with open(pending, "w") as f:
                json.dump({"idem": idem, "values_hash": values_hash,
                           "template_id": template_id, "values": values}, f,
                          ensure_ascii=False, indent=1)

        st, r = self._workbench(f"{LUCY}/api/workbench/{template_id}/runs", method="POST",
                                data={"values": values, "purpose": "raw",
                                      "expected_amount": amount, "revision": revision},
                                extra={"Idempotency-Key": idem})
        if st != 200:
            os.remove(pending)
            if st == 409:
                raise SystemExit("409 价格已变化，请重新报价（价格表或参数 revision 已更新）→ 重跑本命令即可")
            if st == 422:
                raise SystemExit(f"422 参数错误: {str(r)[:300]}")
            raise SystemExit(f"提交失败: {st} {str(r)[:300]}")
        run_id, status = r["run_id"], r.get("status")
        final = os.path.join(self.workdir, "runs", f"{run_id}.json")
        os.replace(pending, final)
        print(f"已提交: run_id={run_id} status={status}（幂等键已存 {os.path.basename(final)}）")

        if wait:
            self.poll(run_id, wait, poll_gap)
        return run_id

    def status(self, run_id):
        st, r = self._workbench(f"{LUCY}/api/runs/{run_id}")
        if st != 200:
            raise SystemExit(f"查询失败: {st} {str(r)[:200]}")
        return r

    def poll(self, run_id, wait, poll_gap=12):
        last = None
        deadline = time.time() + wait
        while time.time() < deadline:
            r = self.status(run_id)
            s = r.get("status")
            if s != last:
                print(f"[{time.strftime('%H:%M:%S')}] {s}")
                last = s
            if s in ("completed", "succeeded", "failed", "canceled"):
                return r
            time.sleep(poll_gap)
        warn("等待超时，任务仍在运行，稍后用 status/download 查询")
        return None

    def download(self, run_id, out_dir=""):
        r = self.status(run_id)
        if r.get("status") != "completed":
            raise SystemExit(f"run 状态为 {r.get('status')}，未到下载阶段")
        outs = r.get("result", {}).get("collected_outputs", [])
        if not outs:
            raise SystemExit("没有产物")
        paths = []
        for i, o in enumerate(outs):
            out = os.path.join(out_dir or os.curdir,
                               f"{run_id[:12]}_{i}.mp4")
            st, n = self._workbench(LUCY + o["url"] if o["url"].startswith("/") else o["url"],
                                    binary_out=out, timeout=300)
            got = hashlib.sha256(open(out, "rb").read()).hexdigest()
            ok = "一致" if got == o.get("sha256") else f"不一致! 本地={got[:16]}"
            print(f"产物 {i}: {out} ({n} bytes) | sha256 {ok}")
            paths.append(out)
        return paths

    def cancel(self, run_id):
        st, r = self._workbench(f"{LUCY}/api/runs/{run_id}/cancel", method="POST", data={})
        if st == 409:
            raise SystemExit("409 任务已开始运行，无法取消（扣费不退）。取消窗口仅在提交后数秒内。")
        if st != 200:
            raise SystemExit(f"取消失败: {st} {str(r)[:200]}")
        print("已取消:", json.dumps(r, ensure_ascii=False)[:200])


# ---------- 登录 ----------
def cmd_login(args):
    workdir = args.workdir
    os.makedirs(workdir, exist_ok=True)
    try:
        from cephalon_api import request as hmac_request, KEY, SECRET
    except Exception as e:
        raise SystemExit(f"HMAC 密钥模块加载失败: {e}")
    if not KEY or not SECRET:
        raise SystemExit("缺少 HMAC 密钥：设置 CEPHALON_PUBLIC_KEY/CEPHALON_PRIVATE_KEY "
                         "环境变量，或创建 cephalon_keys_local.py（参考 cephalon_keys.py 模板）")

    st, body = hmac_request("GET", UC + "/v1/qr", "/v1/qr")
    data = body.get("data", body) if isinstance(body, dict) else {}
    ticket, url = data.get("ticket"), data.get("url")
    if not ticket or not url:
        raise SystemExit(f"取二维码失败: {json.dumps(body, ensure_ascii=False)[:200]}")
    print(f"二维码链接（微信扫码+确认，{data.get('expire_seconds', 300)}s 内有效）:\n{url}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
        png = os.path.join(workdir, "login_qr.png")
        qr.make_image().save(png)
        print(f"二维码图片: {png}")
    except ImportError:
        warn("未安装 qrcode 库（pip install qrcode），请用手机浏览器打开上方链接扫码")

    deadline = time.time() + data.get("expire_seconds", 300)
    print("等待扫码确认…", flush=True)
    while time.time() < deadline:
        st, body = hmac_request("GET", UC + f"/v1/is_ticket_exist?ticket={urllib.parse.quote(ticket)}",
                                "/v1/is_ticket_exist")
        _b = body.get("data", body) if isinstance(body, dict) else {}
        if isinstance(_b, dict) and _b.get("is_exist"):
            break
        time.sleep(3)
    else:
        raise SystemExit("二维码过期，重新运行 login")

    st, body = hmac_request("POST", UC + "/v1/login", "/v1/login",
                            {"way": "ticket", "ticket": ticket, "app_type": "platform"})
    token = (body.get("data", {}) or {}).get("token") if isinstance(body, dict) else None
    if not token:
        raise SystemExit(f"登录失败: {json.dumps(body, ensure_ascii=False)[:300]}")
    tf = os.path.join(workdir, "token.txt")
    with open(tf, "w") as f:
        f.write(token)
    os.chmod(tf, 0o600)
    print(f"登录成功，JWT 已存 {tf}（掩码 {mask(token)}，24h 有效）")
    print(f"后续使用: export LUCY_UC_TOKEN=$(cat {tf}) 或每次加 --token-file {tf}")


# ---------- 参数 ----------
def build_values(args):
    values = {}
    if args.prompt:
        values["prompt"] = args.prompt
    if args.seconds is not None:
        if args.seconds not in (5, 10, 15):
            raise SystemExit("seconds 仅支持 5/10/15")
        values["seconds"] = args.seconds
    if args.ratio is not None:
        if args.ratio not in (1609, 916, 101, 403, 304, 2109):
            raise SystemExit("ratio 仅支持 1609/916/101/403/304/2109")
        values["ratio"] = args.ratio
    if args.resolution is not None:
        if args.resolution not in (480, 544):
            raise SystemExit("resolution 仅支持 480(960p 高)/544(1080p 高)")
        values["resolution"] = args.resolution
    if args.seed is not None:
        values["seed"] = args.seed
    if args.ref_image_size:
        values["ref_image_size"] = args.ref_image_size
    for kv in args.image or []:
        if "=" not in kv:
            raise SystemExit(f"--image 需要键=值形式（如 first_frame=<asset_id>）: {kv}")
        k, v = kv.split("=", 1)
        values[k] = v
    if args.seconds == 15 and args.resolution == 544:
        raise SystemExit("非法组合: " + FORBIDDEN[("15", "544")])
    return values


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workdir", default="lucy_state", help="状态目录（默认 ./lucy_state）")
    p.add_argument("--token-file", default=None, help="user-center JWT 文件（默认 <workdir>/token.txt）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="微信扫码登录")
    sub.add_parser("balance", help="查询 CEP 余额")

    sub.add_parser("templates", help="列出模板")

    up = sub.add_parser("upload", help="上传图片素材")
    up.add_argument("file")

    q = sub.add_parser("quote", help="零消耗报价")
    add_values_args(q)

    s = sub.add_parser("submit", help="提交生成（真实扣费，先报价再确认）")
    add_values_args(s)
    s.add_argument("--yes", action="store_true", help="跳过交互确认")
    s.add_argument("--wait", type=int, default=0, help="提交后等待完成的秒数（0=不等）")

    st = sub.add_parser("status", help="查询 run 状态")
    st.add_argument("run_id")

    dl = sub.add_parser("download", help="下载产物并校验 sha256")
    dl.add_argument("run_id")
    dl.add_argument("-o", "--out-dir", default="")

    c = sub.add_parser("cancel", help="取消（仅 queued 态）")
    c.add_argument("run_id")

    args = p.parse_args()
    os.makedirs(args.workdir, exist_ok=True)

    if args.cmd == "login":
        cmd_login(args)
        return

    token = os.environ.get("LUCY_UC_TOKEN", "")
    tf = args.token_file or os.path.join(args.workdir, "token.txt")
    if not token and os.path.exists(tf):
        token = open(tf).read().strip()
    if not token:
        raise SystemExit(f"缺少 JWT：export LUCY_UC_TOKEN=<token> 或先 python lucy_run.py login")

    api = Api(args.workdir, token)
    if args.cmd == "balance":
        u = api.balance()
        print(f"余额: {u} units = {u / 100:.2f} CEP")
    elif args.cmd == "templates":
        api.ensure_session()
        for t in api.templates():
            keys = " ".join(b["key"] + ("*" if b.get("required") else "")
                            for b in t.get("input_bindings", []))
            print(f"{t['id']}  {t['name']}  [{keys}]")
    elif args.cmd == "upload":
        aid = api.upload_asset(args.file)
        print(f"asset_id: {aid}")
    elif args.cmd == "quote":
        api.ensure_session()
        t = api.resolve_template(api.templates(), args.template)
        vals = build_values(args)
        st, r = api.quote(t["id"], vals)
        print((f"{r['amount']} units = {r['amount'] / 100:.2f} CEP | spec "
               f"{r['spec'].get('width')}x{r['spec'].get('height')} f{r['spec'].get('frames')} "
               f"| revision {r['revision']}") if st == 200 else f"{st} {str(r)[:300]}")
    elif args.cmd == "submit":
        api.ensure_session()
        t = api.resolve_template(api.templates(), args.template)
        vals = build_values(args)
        api.submit(t["id"], vals, assume_yes=args.yes, wait=args.wait)
    elif args.cmd == "status":
        r = api.status(args.run_id)
        show = {k: v for k, v in r.items() if k not in ("values", "workflow")}
        print(json.dumps(show, ensure_ascii=False, indent=1)[:1200])
    elif args.cmd == "download":
        api.download(args.run_id, args.out_dir)
    elif args.cmd == "cancel":
        api.cancel(args.run_id)


def add_values_args(sp):
    sp.add_argument("--template", required=True, help="t2v/i2v/fl2v/r2v 或完整模板 id")
    sp.add_argument("--prompt", required=True, help="画面与声音描述（建议含 overall_soundscape 行）")
    sp.add_argument("--seconds", type=int, default=5, help="5/10/15")
    sp.add_argument("--ratio", type=int, default=1609, help="1609=16:9 等，见 templates")
    sp.add_argument("--resolution", type=int, default=480, help="480=960p 高 / 544=1080p 高")
    sp.add_argument("--seed", type=int, default=None)
    sp.add_argument("--ref-image-size", default=None, help="r2v: match/max")
    sp.add_argument("--image", action="append", metavar="KEY=ASSET_ID",
                    help="图片参数，如 first_frame=<asset_id>，可多次")


if __name__ == "__main__":
    main()
