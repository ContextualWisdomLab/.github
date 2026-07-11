Wait, line 165 is `repository: ${{ github.event.pull_request.head.repo.full_name || github.event.inputs.target_repository || github.repository }}`.
It has `persist-credentials: false`. Why is it "untrusted code checkout"?
Ah!
`score is 0: untrusted code checkout '${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}'`
Wait, `ref: ${{ github.event.pull_request.head.sha || github.event.inputs.pr_head_sha }}` is probably around there. Let's see!
