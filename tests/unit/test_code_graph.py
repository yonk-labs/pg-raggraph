from pg_raggraph.code_graph import CodeEdge, CodeImpact, render_impact_tree


def test_render_tree_with_callers_and_callees():
    res = CodeImpact(
        fqn="pkg.b",
        found=True,
        callers=[CodeEdge("pkg.a", "CALLS", "a() calls b()", 1)],
        callees=[CodeEdge("pkg.c", "CALLS", "", 1)],
    )
    out = render_impact_tree(res)
    assert "pkg.b" in out
    assert "callers:" in out
    assert "pkg.a" in out and "a() calls b()" in out
    assert "callees:" in out
    assert "pkg.c" in out


def test_render_tree_empty_sections_show_none():
    res = CodeImpact(fqn="pkg.x", found=True, callers=[], callees=[])
    out = render_impact_tree(res)
    assert out.count("(none)") == 2


def test_render_tree_marks_transitive_depth():
    res = CodeImpact(
        fqn="pkg.a", found=True, callers=[],
        callees=[CodeEdge("pkg.c", "CALLS", "", 2)],
    )
    out = render_impact_tree(res)
    assert "depth 2" in out
