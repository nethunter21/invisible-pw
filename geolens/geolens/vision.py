"""Vision engine: CLIP / StreetCLIP zero-shot geolocation, clue probes and attention maps.

StreetCLIP (geolocal/StreetCLIP) is an open CLIP ViT-L/14@336 model fine-tuned on
1.1M street-level images for zero-shot geolocation. It is downloaded once from the
Hugging Face hub (no account / key needed) and then runs fully offline.
"""
from __future__ import annotations

import base64
import io
import math
import os
import threading
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageFilter

from . import gazetteer as gz
from .knowledge import PROBES, expand

MODELS = {
    "streetclip": {"repo": "geolocal/StreetCLIP", "label": "StreetCLIP ViT-L/14@336 (best, ~1.7 GB)",
                   "prompt": "A Street View photo in {}."},
    "clip-large": {"repo": "openai/clip-vit-large-patch14", "label": "OpenAI CLIP ViT-L/14 (~1.7 GB)",
                   "prompt": "a photo taken in {}."},
    "clip-base": {"repo": "openai/clip-vit-base-patch32", "label": "OpenAI CLIP ViT-B/32 (fast, ~600 MB)",
                  "prompt": "a photo taken in {}."},
}

ProgressFn = Callable[[str, float], None]


class VisionEngine:
    def __init__(self, model_key: str = "streetclip", cache_dir: str | None = None):
        if model_key not in MODELS and os.path.isdir(model_key):  # custom local CLIP checkpoint
            MODELS[model_key] = {"repo": model_key, "label": f"Local CLIP ({os.path.basename(model_key)})",
                                 "prompt": "a photo taken in {}.", "local": True}
        self.model_key = model_key if model_key in MODELS else "streetclip"
        self.cache_dir = cache_dir
        self.model = None
        self.processor = None
        self.torch = None
        self.device = "cpu"
        self.status = "not loaded"
        self.error: str | None = None
        self.download = {"active": False, "done": 0, "total": 0, "file": ""}
        self._lock = threading.Lock()
        self._text_cache: dict[str, Any] = {}
        self.country_isos: list[str] = []

    # ------------------------------------------------------------------ loading
    def _fetch(self, repo: str) -> str:
        from huggingface_hub import HfApi, hf_hub_download
        files = HfApi().list_repo_files(repo)
        weights = [f for f in files if f.endswith(".safetensors") and "/" not in f]
        if not weights:
            weights = [f for f in files if f == "pytorch_model.bin"]
        wanted = [f for f in files if "/" not in f and (f.endswith(".json") or f.endswith(".txt"))] + weights
        path = None
        dl = self.download
        dl.update(active=True, done=0, total=len(wanted))
        for i, f in enumerate(wanted):
            dl.update(file=f, done=i)
            path = hf_hub_download(repo, f, cache_dir=self.cache_dir)
        dl.update(active=False, done=len(wanted))
        return os.path.dirname(path)

    def _resolve(self, spec: dict) -> str:
        """Local directory of the model weights; downloads them once if missing."""
        if spec.get("local"):
            return spec["repo"]
        try:  # offline first
            from huggingface_hub import snapshot_download
            local = snapshot_download(spec["repo"], cache_dir=self.cache_dir, local_files_only=True)
            if any(f.endswith((".safetensors", ".bin")) for f in os.listdir(local)):
                return local
        except Exception:
            pass
        self.status = "downloading"
        return self._fetch(spec["repo"])

    def load(self) -> bool:
        with self._lock:
            if self.model is not None:
                return True
            try:
                self.status = "loading"
                import torch
                from transformers import CLIPModel, CLIPProcessor
                self.torch = torch
                local = self._resolve(MODELS[self.model_key])
                self.status = "loading"
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
                self.model = CLIPModel.from_pretrained(local).to(self.device).eval()
                self.processor = CLIPProcessor.from_pretrained(local)
                for p in self.model.parameters():
                    p.requires_grad_(False)
                isos = [iso for iso, c in gz.countries().items() if c["area"] >= 300 or iso in ("SG", "HK", "MO", "MT", "AD", "LI")]
                self.country_isos = sorted(isos)
                self.status = "ready"
                self.error = None
                return True
            except Exception as e:  # pragma: no cover - environment dependent
                self.model = None
                self.status = "unavailable"
                self.error = f"{type(e).__name__}: {e}"
                return False

    @property
    def ready(self) -> bool:
        return self.model is not None

    # ------------------------------------------------------------------ embeddings
    def text_emb(self, prompts: list[str]):
        torch = self.torch
        key = "\x1f".join(prompts)
        if key in self._text_cache:
            return self._text_cache[key]
        outs = []
        for i in range(0, len(prompts), 64):
            tok = self.processor(text=prompts[i:i + 64], return_tensors="pt", padding=True, truncation=True)
            tok = {k: v.to(self.device) for k, v in tok.items() if k in ("input_ids", "attention_mask")}
            e = self.model.get_text_features(**tok)
            e = e if isinstance(e, torch.Tensor) else e.pooler_output
            outs.append(e / e.norm(dim=-1, keepdim=True))
        emb = torch.cat(outs)
        self._text_cache[key] = emb
        return emb

    def image_emb(self, images: list[Image.Image]):
        torch = self.torch
        px = self.processor(images=images, return_tensors="pt")["pixel_values"].to(self.device)
        e = self.model.get_image_features(pixel_values=px)
        e = e if isinstance(e, torch.Tensor) else e.pooler_output
        return e / e.norm(dim=-1, keepdim=True)

    def _probs(self, img_e, txt_e):
        scale = float(self.model.logit_scale.exp().clamp(max=100))
        return (scale * img_e @ txt_e.T).softmax(dim=-1).cpu().numpy()

    def country_emb(self, family: str = "mixed"):
        tmpl = MODELS[self.model_key]["prompt"]
        names = [gz.country_name(i) for i in self.country_isos]
        e = self.cached_text([tmpl.format(n) for n in names], "c1") + self.cached_text([f"a photo of a place in {n}." for n in names], "c2")
        if family in ("natural", "waterside", "arid", "snow", "rural_road"):
            e = e + self.cached_text([f"a landscape photo of the countryside in {n}." for n in names], "c3") \
                  + self.cached_text([f"nature and trees in {n}." for n in names], "c4")
        elif family == "urban":
            e = e + self.cached_text([f"a street in a city in {n}." for n in names], "c5")
        return e / e.norm(dim=-1, keepdim=True)

    def option_emb(self, prompt_lists: list[list[str]], tag: str):
        """Prompt ensembling: average the embeddings of several phrasings per option."""
        flat = [p for pl in prompt_lists for p in pl]
        e = self.cached_text(flat, tag)
        out, i = [], 0
        for pl in prompt_lists:
            v = e[i:i + len(pl)].mean(0)
            out.append(v / v.norm())
            i += len(pl)
        return self.torch.stack(out)

    def composition(self, img: Image.Image, n: int = 4) -> dict:
        from .landscape import CELL_LABELS, scene_from_composition
        w, h = img.size
        cells, boxes = [], []
        for r in range(n):
            for c in range(n):
                b = (c * w // n, r * h // n, (c + 1) * w // n, (r + 1) * h // n)
                boxes.append(b)
                cells.append(img.crop(b))
        e = self.image_emb(cells)
        temb = self.option_emb([pl for _, pl in CELL_LABELS], "cells")
        P = self._probs(e, temb)
        labels = [k for k, _ in CELL_LABELS]
        frac = {k: round(float(P[:, i].mean()), 3) for i, k in enumerate(labels)}
        grid = [[labels[int(np.argmax(P[r * n + c]))] for c in range(n)] for r in range(n)]
        fam, fam_label = scene_from_composition(frac)
        return {"fractions": frac, "grid": grid, "family": fam, "family_label": fam_label}

    def option_probs(self, img_e, prompt_lists: list[list[str]], tag: str):
        P = self._probs(img_e, self.option_emb(prompt_lists, tag))
        p = 0.5 * P[0] + 0.5 * P[1:].mean(0) if len(P) > 1 else P[0]
        return p / p.sum(), P

    # ------------------------------------------------------------------ views
    @staticmethod
    def letterbox(img: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
        w, h = img.size
        s = max(w, h)
        mean = tuple(int(x) for x in np.asarray(img).reshape(-1, 3).mean(0))
        canvas = Image.new("RGB", (s, s), mean)
        off = ((s - w) // 2, (s - h) // 2)
        canvas.paste(img, off)
        return canvas, off

    @staticmethod
    def views(img: Image.Image, extra: list | None = None) -> list[dict]:
        w, h = img.size
        out = [{"name": "Full image", "box": [0, 0, w, h], "img": VisionEngine.letterbox(img)[0], "weight": 2.0}]
        for n, b in extra or []:
            out.append({"name": n, "box": list(b), "img": VisionEngine.letterbox(img.crop(tuple(b)))[0], "weight": 1.6})
        boxes = {
            "Top-left": (0, 0, w * 0.6, h * 0.6), "Top-right": (w * 0.4, 0, w, h * 0.6),
            "Bottom-left": (0, h * 0.4, w * 0.6, h), "Bottom-right": (w * 0.4, h * 0.4, w, h),
            "Centre": (w * 0.2, h * 0.2, w * 0.8, h * 0.8),
        }
        if w > 1.4 * h:
            boxes["Left half"] = (0, 0, w * 0.5, h)
            boxes["Right half"] = (w * 0.5, 0, w, h)
        elif h > 1.4 * w:
            boxes["Top half"] = (0, 0, w, h * 0.5)
            boxes["Bottom half"] = (0, h * 0.5, w, h)
        for n, b in boxes.items():
            b = tuple(int(x) for x in b)
            out.append({"name": n, "box": list(b), "img": VisionEngine.letterbox(img.crop(b))[0], "weight": 1.0})
        return out

    # ------------------------------------------------------------------ analysis
    def analyze(self, img: Image.Image, log, extra_views: list | None = None) -> dict:
        res: dict[str, Any] = {}
        views = self.views(img, extra_views)
        with log.timer("vision", f"Encoded {len(views)} image views with {MODELS[self.model_key]['label'].split(' (')[0]}",
                       method="Multi-crop CLIP image embedding",
                       teach="The image is analysed as a whole and as overlapping crops. Crops let the model "
                             "'zoom in' on small details (a sign, a pole, a licence plate) that are lost when the "
                             "whole photo is shrunk to 336×336 px. Comparing crops also shows which part of the "
                             "picture carries the location signal.") as t:
            img_e = self.image_emb([v["img"] for v in views])
            t.detail = ", ".join(v["name"] for v in views)
        res["img_e"] = img_e

        # ---- scene composition (grid labelling) → scene family used to gate the probes
        family = "mixed"
        with log.timer("landscape", "Scene composition (4×4 grid labelling)", method="CLIP per-cell classification over 13 surface classes",
                       teach=__import__("geolens.landscape", fromlist=["TEACH"]).TEACH["composition"]) as t:
            comp = self.composition(img)
            family = comp["family"]
            res["composition"] = comp
            top = sorted(comp["fractions"].items(), key=lambda kv: -kv[1])[:5]
            t.detail = f"Scene: {comp['family_label']} · " + ", ".join(f"{k} {v*100:.0f}%" for k, v in top)
            t.data = comp
        res["family"] = family

        # ---- country classification
        cemb = self.country_emb(family)
        P = self._probs(img_e, cemb)  # views x countries
        ent_max = math.log(P.shape[1])
        weights, per_view = [], []
        for i, v in enumerate(views):
            p = P[i]
            ent = float(-(p * np.log(p + 1e-12)).sum())
            conf = max(0.05, 1 - ent / ent_max)
            wgt = v["weight"] * conf
            weights.append(wgt)
            top = np.argsort(-p)[:3]
            per_view.append({"view": v["name"], "box": v["box"], "confidence": round(conf, 3),
                             "top": [[self.country_isos[j], gz.country_name(self.country_isos[j]), round(float(p[j]), 4)] for j in top]})
        W = np.array(weights)
        agg = (P * W[:, None]).sum(0) / W.sum()
        best = int(np.argmax(agg))
        contrib = (P[:, best] * W) / max(1e-9, (P[:, best] * W).sum())
        for i, pv in enumerate(per_view):
            pv["share_of_top"] = round(float(contrib[i]), 3)
        res["country_probs"] = {self.country_isos[j]: float(agg[j]) for j in range(len(agg))}
        res["views"] = per_view
        top5 = np.argsort(-agg)[:5]
        log.add("vision", "Zero-shot country classification (StreetCLIP-style prompts)",
                method="CLIP image–text similarity over %d countries, entropy-weighted crop fusion" % len(self.country_isos),
                detail="Top: " + ", ".join(f"{gz.country_name(self.country_isos[j])} {agg[j]*100:.1f}%" for j in top5),
                data={"per_view": per_view},
                teach="Each country name is turned into a sentence ('A Street View photo in Kenya.') and embedded. "
                      "The image embedding is compared to every sentence; the closest sentences are the most "
                      "likely countries. Crops whose predictions are confident (low entropy) get more weight. "
                      "'share_of_top' shows how much each crop contributed to the winning country — that is "
                      "the part of the image the decision relied on most.")

        # ---- probes
        probes_out = []
        all_isos = self.country_isos
        for g in PROBES:
            if g["id"] == "scene":
                continue  # replaced by grid composition
            prompts = [[o["prompt"]] + o.get("alt", []) for o in g["options"]]
            temb = self.option_emb(prompts, "probe_" + g["id"])
            gp = self._probs(img_e, temb)  # views x options
            fused = 0.5 * gp[0] + 0.5 * gp[1:].max(0) if len(gp) > 1 else gp[0]
            # option-level scene gating: e.g. "Desert" only for arid scenes
            gate = np.array([1.0 if not o.get("scenes") or family in o["scenes"] else 0.05 for o in g["options"]])
            fused = fused * gate
            fused = fused / fused.sum()
            applicable = not g.get("scenes") or family in g["scenes"]
            order = np.argsort(-fused)
            k = int(order[0])
            opt = g["options"][k]
            thr = max(0.30, 1.8 / len(g["options"]))
            detected = bool(fused[k] >= thr) and applicable
            best_view = int(np.argmax(gp[:, k]))
            entry = {
                "id": g["id"], "title": g["title"], "teach": g["teach"], "weight": g["weight"] if applicable else 0.0,
                "applicable": applicable,
                "detected": detected, "label": opt["label"], "prob": round(float(fused[k]), 3),
                "explain": opt.get("explain", ""),
                "countries": sorted(expand(opt.get("countries", []), all_isos)) if opt.get("countries") else [],
                "best_view": views[best_view]["name"], "best_box": views[best_view]["box"],
                "ranking": [[g["options"][j]["label"], round(float(fused[j]), 3)] for j in order[:4]],
            }
            probes_out.append(entry)
            log.add("clues", f"{g['title']}: {opt['label']}" + ("" if detected else " (weak — ignored)" if applicable else f" (not applicable to a {family} scene)"),
                    method="CLIP zero-shot probe (%d hypotheses)" % len(g["options"]),
                    detail=f"p={fused[k]:.2f} (threshold {thr:.2f}); strongest in: {views[best_view]['name']}; "
                           + "runner-ups: " + ", ".join(f"{l} {p:.2f}" for l, p in entry["ranking"][1:]),
                    data={"ranking": entry["ranking"], "countries": entry["countries"][:40]},
                    teach=g["teach"] + (" — " + opt["explain"] if opt.get("explain") else ""),
                    level="info" if detected else "muted")
        res["probes"] = probes_out
        res["probes"].insert(0, {"id": "scene", "title": "Scene type", "teach": "", "weight": 0.0, "applicable": True,
                                 "detected": True, "label": res["composition"]["family_label"] if "composition" in res else "Mixed",
                                 "prob": 1.0, "explain": "", "countries": [], "best_view": "Full image", "best_box": views[0]["box"],
                                 "ranking": []})
        return res

    def city_similarity(self, img_e, isos: list[str], per_country: int = 120) -> dict:
        tmpl = MODELS[self.model_key]["prompt"]
        cands = []
        for iso in isos:
            cands += gz.cities_of(iso, per_country)
        if not cands:
            return {}
        e = self.cached_text([tmpl.format(f"{c['name']}, {gz.country_name(c['cc'])}") for c in cands], "cityheat")
        P = self._probs(img_e, e)
        p = 0.6 * P[0] + 0.4 * (P[1:].mean(0) if len(P) > 1 else P[0])
        return {(c["name"], c["cc"]): float(v) for c, v in zip(cands, p)}

    # ------------------------------------------------------------------ worldwide landmarks & skylines
    def cached_text(self, prompts: list[str], tag: str):
        import hashlib
        torch = self.torch
        key = hashlib.sha1(("\x1f".join(prompts) + self.model_key).encode()).hexdigest()[:16]
        mem = f"{tag}:{key}"
        if mem in self._text_cache:
            return self._text_cache[mem]
        d = self.cache_dir or os.path.join(os.path.expanduser("~"), ".geolens_cache")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"txt_{tag}_{key}.pt")
        emb = None
        if os.path.exists(path):
            try:
                emb = torch.load(path).to(self.device)
            except Exception:
                emb = None
        if emb is None:
            emb = self.text_emb(prompts)
            try:
                torch.save(emb.cpu(), path)
            except Exception:
                pass
        self._text_cache[mem] = emb
        return emb

    def world_candidates(self) -> list[dict]:
        if hasattr(self, "_world"):
            return self._world
        from .landmarks import TOURIST_CITIES, unique_prompt_entries
        out = []
        for e in unique_prompt_entries():
            out.append({"type": "landmark", "name": e["name"], "city": e["city"], "cc": e["cc"], "lat": e["lat"],
                        "lon": e["lon"], "kind": e["kind"]})
        seen = set()
        for c in sorted(gz.all_cities(), key=lambda c: -c["pop"]):
            if c["pop"] < 1_000_000:
                break
            seen.add((c["name"], c["cc"]))
            out.append({"type": "city", "name": c["name"], "city": c["name"], "cc": c["cc"], "lat": c["lat"], "lon": c["lon"]})
        for n, cc, la, lo in TOURIST_CITIES:
            if (n, cc) not in seen:
                out.append({"type": "city", "name": n, "city": n, "cc": cc, "lat": la, "lon": lo})
        self._world = out
        return out

    def world_places(self, img_e, log, night: bool = False) -> list[dict]:
        cands = self.world_candidates()
        tmpl = MODELS[self.model_key]["prompt"]
        p1, p2 = [], []
        for c in cands:
            country = gz.country_name(c["cc"])
            if c["type"] == "landmark":
                p1.append(f"a photo of {c['name']}, {c['city']}, {country}.")
                p2.append(f"{c['name']} in {c['city']}" + (" at night." if night else "."))
            else:
                p1.append(tmpl.format(f"{c['name']}, {country}"))
                p2.append(f"the skyline of {c['name']}, {country}" + (" at night." if night else "."))
        e = self.cached_text(p1, "world1") + self.cached_text(p2, "world2" + ("n" if night else ""))
        e = e / e.norm(dim=-1, keepdim=True)
        P = self._probs(img_e, e)
        p = 0.5 * P[0] + 0.5 * (P[1:].max(0) if len(P) > 1 else P[0])
        p = p / p.sum()
        order = np.argsort(-p)[:12]
        out = [dict(cands[j], p=float(p[j])) for j in order]
        log.add("vision", "Worldwide landmark & skyline recognition",
                method=f"CLIP zero-shot over {len(cands)} landmarks, casinos/hotels and major/tourist cities"
                       + (" (night-time prompts)" if night else ""),
                detail=", ".join(f"{o['name']} ({o['cc']}) {o['p']*100:.1f}%" for o in out[:6]),
                data=[{k: o[k] for k in ("type", "name", "city", "cc", "p")} for o in out],
                teach="Instead of only asking 'which country?', the image is compared directly with hundreds of "
                      "named places — famous buildings, casino resorts, skylines. A country classifier can "
                      "confuse two night skylines of glass towers (Las Vegas vs. Riyadh), but a direct match "
                      "with 'the Las Vegas Strip at night' or a specific casino is far more discriminative.")
        return out

    def refine_cities(self, img_e, top_countries: list[tuple[str, float]], extra: list[dict], log) -> list[dict]:
        cands: list[dict] = []
        for iso, p in top_countries:
            for c in gz.cities_of(iso, 30):
                cands.append(dict(c, prior=p))
        seen = {(c["name"], c["cc"]) for c in cands}
        for c in extra:
            if c.get("type") == "city" and (c["name"], c["cc"]) not in seen:
                cands.append(dict(c, prior=0.3))
        if not cands:
            return []
        tmpl = MODELS[self.model_key]["prompt"]
        temb = self.text_emb([tmpl.format(f"{c['name']}, {gz.country_name(c['cc'])}") for c in cands])
        p = self._probs(img_e[:1], temb)[0] * 0.6 + self._probs(img_e[1:], temb).mean(0) * 0.4
        score = p * np.array([c["prior"] for c in cands])
        score = score / score.sum()
        order = np.argsort(-score)[:10]
        out = [dict(cands[j], score=float(score[j]), clip=float(p[j])) for j in order]
        log.add("vision", "City-level refinement",
                method=f"CLIP similarity against {len(cands)} major cities of the top countries, × country posterior",
                detail=", ".join(f"{c['name']} ({c['cc']}) {c['score']*100:.1f}%" for c in out[:5]),
                teach="Once the country is narrowed down, the same zero-shot trick is repeated with city names. "
                      "This works best for big, visually distinctive cities; for rural scenes the result is "
                      "better read as 'the region around this city'.")
        return out

    # ------------------------------------------------------------------ attention
    def saliency(self, img: Image.Image, text: str) -> dict | None:
        """Gradient×activation map of the last ViT block for a text query (Grad-CAM for ViT)."""
        torch = self.torch
        sq, (ox, oy) = self.letterbox(img)
        px = self.processor(images=[sq], return_tensors="pt")["pixel_values"].to(self.device)
        px.requires_grad_(True)
        t = self.text_emb([text])[0]
        with torch.enable_grad():
            vm = self.model.vision_model
            out = vm(pixel_values=px, output_hidden_states=True)
            act = out.hidden_states[-2]
            act.retain_grad()
            pooled = out.pooler_output
            e = self.model.visual_projection(pooled)
            e = e / e.norm(dim=-1, keepdim=True)
            (e[0] @ t).backward()
        g = act.grad[0, 1:]
        a = act[0, 1:].detach()
        cam = torch.relu((g * a).sum(-1)).cpu().numpy()
        n = int(round(math.sqrt(cam.shape[0])))
        cam = cam[: n * n].reshape(n, n)
        if cam.max() <= 0:
            return None
        cam = cam / cam.max()
        S = sq.size[0]
        m = Image.fromarray((cam * 255).astype(np.uint8)).resize((S, S), Image.BICUBIC)
        m = m.filter(ImageFilter.GaussianBlur(S / (n * 2.5)))
        m = m.crop((ox, oy, ox + img.size[0], oy + img.size[1]))
        arr = np.asarray(m).astype(np.float32) / 255.0
        arr = arr / max(1e-6, arr.max())
        # region shares on a 3x3 grid
        h, w = arr.shape
        names = [["top-left", "top-centre", "top-right"], ["middle-left", "centre", "middle-right"],
                 ["bottom-left", "bottom-centre", "bottom-right"]]
        tot = arr.sum() + 1e-9
        regions = []
        for r in range(3):
            for c in range(3):
                s = arr[r * h // 3:(r + 1) * h // 3, c * w // 3:(c + 1) * w // 3].sum() / tot
                regions.append({"region": names[r][c], "share": round(float(s), 3)})
        regions.sort(key=lambda x: -x["share"])
        return {"png": _colorize(arr), "regions": regions, "grid": n}


def _colorize(a: np.ndarray) -> str:
    """Inferno-like colormap with alpha ∝ intensity → base64 PNG overlay."""
    stops = np.array([[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]], np.float32)
    x = np.clip(a, 0, 1) * (len(stops) - 1)
    i = np.clip(x.astype(int), 0, len(stops) - 2)
    f = (x - i)[..., None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    alpha = (np.clip(a, 0, 1) ** 0.8 * 210)[..., None]
    rgba = np.concatenate([rgb, alpha], -1).astype(np.uint8)
    im = Image.fromarray(rgba, "RGBA")
    if max(im.size) > 900:
        im.thumbnail((900, 900))
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
