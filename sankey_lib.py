from dataclasses import dataclass, field

BLANK_CANDIDATE = None


@dataclass
class SankeyData:
    """Container for data useful for creating Sankey Plots."""

    source: list = field(default_factory=list)
    target: list = field(default_factory=list)
    value: list = field(default_factory=list)
    link_color: list = field(default_factory=list)

    labels: list = field(default_factory=list)
    node_color: list = field(default_factory=list)


def results_to_sankey(results, candidates, node_palette, link_palette):

    assert len(node_palette) == len(link_palette)
    num_colors = len(node_palette)

    # Add a blank candidate for blank/exhausted ballots.
    candidates = candidates.copy()
    candidates.append(BLANK_CANDIDATE)

    data = SankeyData()
    num_candidates = len(candidates)

    def name(c):
        return "-exhausted-" if c is BLANK_CANDIDATE else c.name

    labels = [name(c) for c in candidates]
    node_color = [node_palette[idx % num_colors] for idx in range(num_candidates)]
    num_rounds = len(results.rounds)

    data.node_color = node_color * num_rounds
    data.labels = labels * num_rounds

    for rnd, rnd_result in enumerate(results.rounds[:-1]):
        counts = {r.candidate: r.number_of_votes for r in rnd_result.candidate_results}
        counts[BLANK_CANDIDATE] = rnd_result.number_of_blank_votes

        offset = rnd * num_candidates
        for src_idx, src in enumerate(candidates):
            transfers = rnd_result.transfers.get(src)
            if transfers:
                for tgt_idx, tgt in enumerate(candidates):
                    if tgt in transfers:
                        data.source.append(src_idx + offset)
                        data.target.append(tgt_idx + offset + num_candidates)
                        data.value.append(transfers[tgt])
                        data.link_color.append(link_palette[src_idx % num_colors])
            else:
                data.source.append(src_idx + offset)
                data.target.append(src_idx + offset + num_candidates)
                data.value.append(counts[src])
                data.link_color.append(link_palette[src_idx % num_colors])

    return data
