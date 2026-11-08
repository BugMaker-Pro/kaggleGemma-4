## Locate the code using issue evidence

Start from concrete evidence in the issue: identifiers, exception text, traceback frames, file paths, parameter names, and quoted source lines. Search these cues before broad conceptual queries. If the issue supplies no exact cue, form a small number of distinct searches from the reported behavior and verify results by reading code.

Maintain a short working list of plausible definitions and the evidence for each. Keep useful existing leads when expanding the search. A hit in the right file does not establish that you found the responsible definition: read the relevant function or class and enough surrounding code to understand the behavior. Broaden the read when module-level behavior, initialization, new definitions, or a caller/callee relationship matters.

When a search fails, vary the evidence channel rather than repeating the same query. Do not repeatedly replace supported candidates with weakly related results. Use code inspection and a focused reproduction to decide where to edit. The candidate list is a reasoning aid, not a requirement to inspect a fixed number of symbols regardless of budget.

After identifying a concrete symbol, use an available graph tool for a focused one-hop lookup only when an unresolved caller, callee, or inheritance relationship could explain the behavior. Treat neighbors as additional leads, not evidence that existing candidates should be discarded. Read the relevant code before promoting a neighbor. Do not automatically traverse multiple hops or expand many seeds. If the graph is absent, incomplete, or the query fails, continue with text search and code reading. Do not invoke optional embedding-neighbor tools in this arm.
