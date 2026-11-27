"""Create a tiny random CLIP checkpoint for offline tests (no downloads)."""
import json, os, sys
from transformers import CLIPConfig, CLIPModel, CLIPTokenizer, CLIPImageProcessor, CLIPProcessor


def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b); cs.append(256 + n); n += 1
    return dict(zip(bs, [chr(c) for c in cs]))

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
chars = list(bytes_to_unicode().values())
vocab = {}
for c in chars:
    vocab[c] = len(vocab)
for c in chars:
    vocab[c + "</w>"] = len(vocab)
vocab["<|startoftext|>"] = len(vocab); vocab["<|endoftext|>"] = len(vocab)
json.dump(vocab, open(f"{out}/vocab.json", "w"))
open(f"{out}/merges.txt", "w").write("#version: 0.2\n")
tok = CLIPTokenizer(f"{out}/vocab.json", f"{out}/merges.txt")
cfg = CLIPConfig(text_config=dict(vocab_size=len(vocab), hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                                  num_attention_heads=2, max_position_embeddings=77),
                 vision_config=dict(hidden_size=32, intermediate_size=64, num_hidden_layers=2, num_attention_heads=2,
                                    image_size=224, patch_size=32), projection_dim=32)
CLIPModel(cfg).save_pretrained(out)
CLIPProcessor(image_processor=CLIPImageProcessor(), tokenizer=tok).save_pretrained(out)
print("ok", out)
