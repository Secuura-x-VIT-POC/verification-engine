from __future__ import annotations

from collections import defaultdict

from .models import BoundingBox, EvidenceLine, SpatialTextToken


def build_evidence_lines(spatial_text_map: list[SpatialTextToken]) -> list[EvidenceLine]:
    lines: list[EvidenceLine] = []
    by_page: dict[int, list[tuple[int, SpatialTextToken]]] = defaultdict(list)
    for index, token in enumerate(spatial_text_map):
        by_page[token.page].append((index, token))

    for page, indexed_tokens in by_page.items():
        indexed_tokens.sort(key=lambda item: (round(item[1].bbox[1], 1), item[1].bbox[0]))
        current_tokens: list[SpatialTextToken] = []
        current_indices: list[int] = []
        current_y: float | None = None
        for index, token in indexed_tokens:
            token_y = float(token.bbox[1])
            if current_y is None or abs(token_y - current_y) <= 4.5:
                current_tokens.append(token)
                current_indices.append(index)
                current_y = token_y if current_y is None else min(current_y, token_y)
                continue
            lines.append(_tokens_to_line(page, current_tokens, current_indices))
            current_tokens = [token]
            current_indices = [index]
            current_y = token_y
        if current_tokens:
            lines.append(_tokens_to_line(page, current_tokens, current_indices))
    return lines


def page_tokens(spatial_text_map: list[SpatialTextToken], page: int) -> list[SpatialTextToken]:
    return [token for token in spatial_text_map if token.page == page]


def extract_tables_from_lines(lines: list[EvidenceLine]) -> dict[int, list[list[list[str]]]]:
    tables: dict[int, list[list[list[str]]]] = defaultdict(list)
    current_table: list[list[str]] = []
    current_page: int | None = None

    for line in lines:
        cells = [part.strip() for part in line.text.split("  ") if part.strip()]
        if len(cells) < 2 and "\t" in line.text:
            cells = [part.strip() for part in line.text.split("\t") if part.strip()]

        if len(cells) >= 2:
            if current_page is None:
                current_page = line.page
            if current_page != line.page and current_table:
                tables[current_page].append(current_table)
                current_table = []
                current_page = line.page
            current_table.append(cells)
            continue

        if current_table and current_page is not None:
            tables[current_page].append(current_table)
            current_table = []
            current_page = None

    if current_table and current_page is not None:
        tables[current_page].append(current_table)

    return dict(tables)


def _tokens_to_line(page: int, tokens: list[SpatialTextToken], token_indices: list[int]) -> EvidenceLine:
    return EvidenceLine(
        page=page,
        text=" ".join(token.text for token in tokens).strip(),
        bbox=BoundingBox(
            page=page,
            x0=round(min(float(token.bbox[0]) for token in tokens), 2),
            y0=round(min(float(token.bbox[1]) for token in tokens), 2),
            x1=round(max(float(token.bbox[2]) for token in tokens), 2),
            y1=round(max(float(token.bbox[3]) for token in tokens), 2),
        ),
        token_indices=list(token_indices),
        source=tokens[0].source if tokens else "native_text",
    )
