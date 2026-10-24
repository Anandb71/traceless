"""Minimal CLIP ViT-L/14 vision tower (HF state-dict compatible).

Written out (~80 lines) instead of importing `transformers`: faster cold start,
no surprise version drift, and direct access to patch tokens for the dense
clue maps. Verified numerically against transformers' CLIPVisionModelWithProjection
in tests/test_clip_vit.py when transformers is importable.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import nn


class _Layer(nn.Module):
    def __init__(self, d: int, heads: int, mlp: int):
        super().__init__()
        self.heads = heads
        self.layer_norm1 = nn.LayerNorm(d, eps=1e-5)
        self.layer_norm2 = nn.LayerNorm(d, eps=1e-5)
        self.self_attn = nn.Module()
        for n in ("q_proj", "k_proj", "v_proj", "out_proj"):
            setattr(self.self_attn, n, nn.Linear(d, d))
        self.mlp = nn.Module()
        self.mlp.fc1 = nn.Linear(d, mlp)
        self.mlp.fc2 = nn.Linear(mlp, d)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, n, d = x.shape
        h = self.layer_norm1(x)
        a = self.self_attn
        q = a.q_proj(h).view(b, n, self.heads, -1).transpose(1, 2)
        k = a.k_proj(h).view(b, n, self.heads, -1).transpose(1, 2)
        v = a.v_proj(h).view(b, n, self.heads, -1).transpose(1, 2)
        o = F.scaled_dot_product_attention(q, k, v).transpose(1, 2).reshape(b, n, d)
        x = x + a.out_proj(o)
        h = self.mlp.fc1(self.layer_norm2(x))
        h = h * torch.sigmoid(1.702 * h)  # quick_gelu
        return x + self.mlp.fc2(h)


class CLIPVision(nn.Module):
    def __init__(self, d=1024, layers=24, heads=16, mlp=4096, patch=14, image=224, proj=768):
        super().__init__()
        self.patch = patch
        self.grid = image // patch
        vm = nn.Module()
        vm.embeddings = nn.Module()
        vm.embeddings.class_embedding = nn.Parameter(torch.zeros(d))
        vm.embeddings.patch_embedding = nn.Conv2d(3, d, patch, patch, bias=False)
        vm.embeddings.position_embedding = nn.Embedding(self.grid**2 + 1, d)
        vm.pre_layrnorm = nn.LayerNorm(d, eps=1e-5)
        vm.encoder = nn.Module()
        vm.encoder.layers = nn.ModuleList(_Layer(d, heads, mlp) for _ in range(layers))
        vm.post_layernorm = nn.LayerNorm(d, eps=1e-5)
        self.vision_model = vm
        self.visual_projection = nn.Linear(d, proj, bias=False)

    def _pos(self, gh: int, gw: int) -> torch.Tensor:
        pe = self.vision_model.embeddings.position_embedding.weight
        if gh == self.grid and gw == self.grid:
            return pe
        cls, grid = pe[:1], pe[1:]
        g = int(math.sqrt(grid.shape[0]))
        grid = grid.reshape(1, g, g, -1).permute(0, 3, 1, 2)
        grid = F.interpolate(grid, size=(gh, gw), mode="bicubic", align_corners=False)
        return torch.cat([cls, grid.permute(0, 2, 3, 1).reshape(gh * gw, -1)])

    def forward(self, x: torch.Tensor, return_tokens: bool = False):
        vm = self.vision_model
        p = vm.embeddings.patch_embedding(x)  # (B, D, gh, gw)
        b, d, gh, gw = p.shape
        p = p.flatten(2).transpose(1, 2)
        cls = vm.embeddings.class_embedding.expand(b, 1, d)
        h = torch.cat([cls, p], dim=1) + self._pos(gh, gw)
        h = vm.pre_layrnorm(h)
        for layer in vm.encoder.layers:
            h = layer(h)
        pooled = vm.post_layernorm(h[:, 0])
        emb = self.visual_projection(pooled)
        if return_tokens:
            return emb, h
        return emb


def dense_features(model: CLIPVision, x: torch.Tensor) -> torch.Tensor:
    """ClearCLIP-style dense patch embeddings (Lan et al., ECCV 2024).

    Last block: query-query attention, no residual, no FFN; then the usual
    post-LN + projection. Returns L2-normalized (B, gh, gw, proj).
    """
    vm = model.vision_model
    p = vm.embeddings.patch_embedding(x)
    b, d, gh, gw = p.shape
    p = p.flatten(2).transpose(1, 2)
    cls = vm.embeddings.class_embedding.expand(b, 1, d)
    h = vm.pre_layrnorm(torch.cat([cls, p], dim=1) + model._pos(gh, gw))
    for layer in vm.encoder.layers[:-1]:
        h = layer(h)
    last = vm.encoder.layers[-1]
    a = last.self_attn
    z = last.layer_norm1(h)
    n = z.shape[1]
    q = a.q_proj(z).view(b, n, last.heads, -1).transpose(1, 2)
    v = a.v_proj(z).view(b, n, last.heads, -1).transpose(1, 2)
    o = F.scaled_dot_product_attention(q, q, v).transpose(1, 2).reshape(b, n, d)
    o = a.out_proj(o)
    e = model.visual_projection(vm.post_layernorm(o[:, 1:]))
    return F.normalize(e, dim=-1).reshape(b, gh, gw, -1)
