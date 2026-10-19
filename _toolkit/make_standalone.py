"""Bọc trang Word Practice thành file HTML độc lập để đưa lên web (GitHub Pages / Netlify / Cloudflare Pages)."""
import sys, re, html
src, out, desc = sys.argv[1], sys.argv[2], sys.argv[3]
body = open(src, encoding="utf-8").read()
title = re.search(r"<title>(.*?)</title>", body).group(1)
head = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#121F55">
<meta name="description" content="{html.escape(desc)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title} · Fun English Tales">
<meta property="og:description" content="{html.escape(desc)}">
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}img{{max-width:100%}}[hidden]{{display:none!important}}</style>
'''
body = body.replace("<header class=\"band\">", "</head>\n<body>\n<header class=\"band\">", 1)
open(out, "w", encoding="utf-8").write(head + body + "\n</body>\n</html>\n")
print("STANDALONE_OK", out)
