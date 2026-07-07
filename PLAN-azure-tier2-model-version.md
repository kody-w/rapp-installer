# PLAN: Tier 2 ARM template deploys a model/version pair that cannot exist

**Rank: 4 of 5.**

## Goal

`azuredeploy.json` deployed with its own defaults must succeed. Today it cannot: the
default model is `gpt-5.2-chat` but the deployment resource hardcodes model **version
`"2024-08-06"`** — the gpt-4o version string — so the "Deploy to Azure" button fails for
every user who accepts defaults, and for every `o1`/`o1-mini`/`o3-mini` selection too.

## Files to touch

- `azuredeploy.json` — parameters block (`:37-52` area) and the OpenAI deployment
  resource (`:220-223`)
- `deploy.sh`, `deploy.ps1` — only if they prompt for/pass model parameters (they pass
  the template URI; verify whether they surface a model choice)
- `README.md:113`, `skill.md:235`, landing-page Tier-2 copy — wording only (coordinate
  with PLAN-web-truth-pass.md; if both plans execute, do the wording once)

## Current state (verified)

- `azuredeploy.json:37` `openAIModelName` default `gpt-5.2-chat`; `:42-44` allowed
  values include `o1`, `o1-mini`, `o3-mini`; `:52` `openAIDeploymentName` defaults to
  the same.
- `azuredeploy.json:220-223`:
  ```json
  "model": { "format": "OpenAI", "name": "[parameters('openAIModelName')]", "version": "2024-08-06" }
  ```
  Version is not parameterized and not per-model. `2024-08-06` is valid **only for
  gpt-4o**.
- App setting `AZURE_OPENAI_API_VERSION` = `2025-01-01-preview` (`:314`) — fine, leave it.
- Region is parameterized with a 16-region allowlist — fine, leave it.

## Implementation order

1. **Discover the real version strings** for every model in the `allowedValues` list.
   Run (needs `az login`; any subscription with Cognitive Services access):
   ```bash
   az cognitiveservices model list -l eastus2 -o json \
     | python3 -c "import json,sys; [print(m['model']['name'], m['model']['version']) for m in json.load(sys.stdin) if m['model'].get('name')]" \
     | sort -u
   ```
   Record the current version for each allowed model. **If a model in `allowedValues`
   no longer appears in the catalog, remove it from `allowedValues`** rather than
   guessing a version.
2. **Add a variables map + parameter.** In `azuredeploy.json`:
   - New parameter `openAIModelVersion`, type string, `"defaultValue": ""`, description
     "Model version. Leave empty to use the known-good version for the selected model."
   - New variable:
     ```json
     "modelDefaultVersions": {
       "gpt-5.2-chat": "<from step 1>",
       "gpt-4o": "2024-08-06",
       "o1": "<from step 1>",
       "o1-mini": "<from step 1>",
       "o3-mini": "<from step 1>"
     }
     ```
     (one entry per surviving allowedValue, no extras)
   - Change the resource:
     ```json
     "version": "[if(empty(parameters('openAIModelVersion')), variables('modelDefaultVersions')[parameters('openAIModelName')], parameters('openAIModelVersion'))]"
     ```
3. **Check the SKU.** The deployment resource's `sku` (near `:225`) — o-series and
   gpt-5.x models commonly require `GlobalStandard` while older models use `Standard`.
   Verify per model in the same `az cognitiveservices model list` output
   (`skuName`/deployment info). If they differ across the allowed set, add a
   `modelDefaultSkus` variable map keyed the same way; otherwise leave the sku alone
   and note in the parameter description which sku family the template assumes.
4. **deploy.sh / deploy.ps1** — read both; they already have region-quota retry menus.
   If they pass `openAIModelName`, no change needed (version now auto-resolves). If they
   hardcode nothing model-related, no change.
5. **Docs wording** — see PLAN-web-truth-pass.md step 4; if executing this plan alone,
   update README.md:113 and skill.md:235 to name the actual default model.

## Edge cases a weaker model would miss

- **ARM `if()` evaluates both branches in some older API versions?** No — `if()` is
  lazy for invalid references, but `variables('modelDefaultVersions')[parameters(...)]`
  with a model name missing from the map fails at **template validation**, not
  deployment. So the map MUST cover exactly the `allowedValues` set — adding an allowed
  model without a map entry breaks even explicit-version deployments. Add a comment in
  the template's metadata description noting the two must stay in lockstep.
- **`openAIDeploymentName` defaults to the model name** (`:52`) and existing users may
  have `.env`/app settings expecting deployment name == model name. Don't rename either
  default.
- **Model retirement is the reason this broke**: hardcoded "2024-08-06" was correct when
  gpt-4o was the default. The empty-string-parameter + map pattern means the next model
  bump touches one map entry, not a hidden literal.
- **Do not bump resource `apiVersion`s** while you're in the file — Cognitive Services
  `2023-05-01` is validated and working; a drive-by bump is how templates break silently.
- **`azuredeploy.json` is consumed by URL** from three places: the landing-page portal
  button (`index.html:333`), `deploy.sh:18`, `deploy.ps1:16` — all point at
  `raw.../main/azuredeploy.json`. Changes only go live at release-merge; test from the
  branch URL first (portal accepts any raw URL).

## Acceptance criteria

1. `python3 -m json.tool azuredeploy.json > /dev/null` (valid JSON).
2. `az deployment group validate -g <test-rg> --template-file azuredeploy.json`
   succeeds with **all defaults** (no parameters passed).
3. `az deployment group what-if` (or a real deploy to a scratch RG) with defaults shows
   the OpenAI deployment resource with a version string that is NOT `2024-08-06`-on-
   gpt-5.2-chat; then repeat once with `--parameters openAIModelName=gpt-4o` and confirm
   version resolves to `2024-08-06`.
4. Optional full check: deploy to a scratch resource group, confirm the Function App
   comes up, then `az group delete` the scratch RG.
5. Branch pushed; **no push to main** — the raw-URL consumers only see this after the
   maintainer's release merge.
