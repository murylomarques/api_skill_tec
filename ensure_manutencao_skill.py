# ensure_manutencao_skill.py
#
# Requisitos:
#   pip install requests
#   (e seus módulos existentes)
#     - sf_auth.py: get_salesforce_token, get_auth_headers
#     - sf_query.py: get_all_query_results
#
# Uso:
#   python ensure_manutencao_skill.py --listar-grupos
#
#   python ensure_manutencao_skill.py --id-ou-nome "NOME" --grupo "Retirada" --modo 1
#   python ensure_manutencao_skill.py --ids-ou-nomes "NOME1" "NOME2" "0Hn..." --grupo "Ativação" --modo 3
#   python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 1 --dry-run
#
# Flags úteis:
#   --ativar-inativo          (tenta ativar se estiver inativo)
#   --dry-run                 (não executa, só mostra preview)
#   --sem-cor                 (desativa cores)
#   --selecionar-skills       (deixa escolher 1,2,5 dentro do grupo; senão aplica TODAS)

import os
import argparse
import requests
from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, request

# opcional: se tiver python-dotenv instalado
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from sf_auth import get_salesforce_token, get_auth_headers
from sf_query import get_all_query_results

API_VERSION = "v65.0"

# =========================
# CREDENCIAIS (NÃO COMMITAR)
# =========================
# ====== Credenciais (NÃO commitar) ======
SF_DOMAIN = os.getenv("SF_DOMAIN", "")
SF_CLIENT_ID = os.getenv("SF_CLIENT_ID", "")
SF_CLIENT_SECRET = os.getenv("SF_CLIENT_SECRET", "")
SF_USERNAME = os.getenv("SF_USERNAME", "")
SF_PASSWORD = os.getenv("SF_PASSWORD", "")
# =======================================

# ============================================================
# MAPA DE GRUPOS (SEU PADRÃO) -> MasterLabel exato da Skill
# ============================================================
GROUPS_MAP = {
    "Ativação": [
        "Ativação",
        "Chip",
        "Mesh",
        "PME",
        "TV",
    ],
    "Manutenção Corretiva": [
        "Chip",
        "Manutenção",
        "Manutenção Garantia",
        "Mesh",
        "MotoDesk",
        "PME",
        "TV",
        "OS critica",
    ],
    "Manutenção Preventiva": [
        "Manutenção",
        "Mesh",
        "PME",
        "TV",
    ],
    "Outros": [
        "Alteração de plano",
        "Chip",
        "Mesh",
        "Migração",
        "Migração - Zhone",
        "PME",
        "Serviços Adicionais",
        "TV",
    ],
    "Mudança": [
        "Chip",
        "Mesh",
        "Mudança de endereço",
        "PME",
        "TV",
        "OS critica",
    ],
    "Retirada": [
        "Chip",
        "MotoDesk",
        "PME",
        "Retirada de Equipamento - Compulsório",
        "Retirada de Equipamento - Voluntário",
        "TV",
    ],
}

GROUP_ORDER = ["Ativação", "Manutenção Corretiva", "Manutenção Preventiva", "Outros", "Mudança", "Retirada"]

# =========================
# CORES (ANSI)
# =========================
def c(text: str, code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"

def ok(text: str, enabled=True) -> str:
    return c(text, "92", enabled)  # verde

def warn(text: str, enabled=True) -> str:
    return c(text, "93", enabled)  # amarelo

def err(text: str, enabled=True) -> str:
    return c(text, "91", enabled)  # vermelho

def bold(text: str, enabled=True) -> str:
    return c(text, "1", enabled)   # negrito



# =========================
# UI "PRO" (BOX / LAYOUT)
# =========================
def term_width(default=88) -> int:
    try:
        import shutil
        return max(60, min(140, shutil.get_terminal_size((default, 20)).columns))
    except Exception:
        return default

def hr(ch="─", enabled=True):
    w = term_width()
    print(c(ch * w, "90", enabled))

def box(title: str, lines: list[str], enabled=True, accent_code="96"):
    """Desenha um box com bordas usando box-drawing."""
    w = term_width()
    inner = w - 4  # bordas + espaços
    top = f"┌{'─' * (w-2)}┐"
    bot = f"└{'─' * (w-2)}┘"
    print(c(top, "90", enabled))
    t = f" {title} "
    t = t[:inner]
    print(f"│{c(t.ljust(inner), accent_code, enabled)}│")
    print(c(f"├{'─' * (w-2)}┤", "90", enabled))

    for raw in lines:
        ln = "" if raw is None else str(raw)

        # linha vazia: imprime uma linha em branco no box
        if ln == "":
            print(f"│ {'':{inner-1}}│")
            continue

        # wrap simples no tamanho do box
        while ln:
            chunk = ln[:inner]
            ln = ln[inner:]
            print(f"│ {chunk.ljust(inner-1)}│")

    print(c(bot, "90", enabled))

def badge(text: str, kind="info", enabled=True) -> str:
    if kind == "ok":
        return ok(f"[{text}]", enabled)
    if kind == "warn":
        return warn(f"[{text}]", enabled)
    if kind == "err":
        return err(f"[{text}]", enabled)
    return c(f"[{text}]", "96", enabled)

def big_header(app_name="ENSURE SKILLS", subtitle="Salesforce Field Service", enabled=True):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    box(
        title=f"{app_name}  {badge('CLI', 'info', enabled)}",
        lines=[
            f"{subtitle}",
            f"🕒 {now}",
            "✨ UI PRO MODE: ON",
        ],
        enabled=enabled,
        accent_code="95",
    )

# =========================
# HELPERS SF
# =========================
def normalize_records(res):
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        return res.get("records", [])
    return []

def soql(instance_url, headers, query: str):
    res = get_all_query_results(instance_url=instance_url, auth_headers=headers, query=query)
    return normalize_records(res)

def sf_login_or_die():
    missing = []
    for k, v in [("SF_CLIENT_ID", SF_CLIENT_ID), ("SF_CLIENT_SECRET", SF_CLIENT_SECRET),
                 ("SF_USERNAME", SF_USERNAME), ("SF_PASSWORD", SF_PASSWORD), ("SF_DOMAIN", SF_DOMAIN)]:
        if not v:
            missing.append(k)
    if missing:
        raise SystemExit(f"❌ Faltam variáveis de ambiente/.env: {', '.join(missing)}")

    token_data = get_salesforce_token(
        domain=SF_DOMAIN,
        client_id=SF_CLIENT_ID,
        client_secret=SF_CLIENT_SECRET,
        username=SF_USERNAME,
        password=SF_PASSWORD
    )

    if not isinstance(token_data, dict) or not token_data.get("access_token"):
        raise SystemExit("❌ Falha ao autenticar: access_token não retornou (invalid_grant).")

    headers = get_auth_headers(token_data)
    if not isinstance(headers, dict) or "Authorization" not in headers:
        raise SystemExit("❌ Falha ao autenticar: header Authorization não retornou.")

    instance_url = token_data.get("instance_url") or SF_DOMAIN
    return instance_url, headers

def sf_login_for_api():
    try:
        return sf_login_or_die()
    except SystemExit as e:
        raise RuntimeError(str(e))


# =========================
# SKILLS / GRUPOS (RESOLVE MasterLabel -> SkillId)
# =========================
def list_all_skills(instance_url, headers, limit=2000):
    q = f"""
        SELECT Id, MasterLabel, DeveloperName
        FROM Skill
        WHERE IsDeleted = false
        ORDER BY MasterLabel
        LIMIT {limit}
    """
    return soql(instance_url, headers, q)

def build_label_to_id(all_skills):
    d = {}
    for s in all_skills:
        ml = s.get("MasterLabel")
        sid = s.get("Id")
        if ml and sid:
            d[ml.strip()] = sid
    return d

def build_groups_resolved(label_to_id):
    """
    Retorna:
      groups_resolved[group] = [{label,id},...]
      missing[group] = [label,...]  (labels do map que não existem na org / MasterLabel diferente)
    """
    groups_resolved = {}
    missing = {}
    for g in GROUP_ORDER:
        groups_resolved[g] = []
        missing[g] = []
        for label in GROUPS_MAP.get(g, []):
            sid = label_to_id.get(label)
            if not sid:
                missing[g].append(label)
            else:
                groups_resolved[g].append({"label": label, "id": sid})
    return groups_resolved, missing


# =========================
# TECH / LINKS
# =========================
def get_skill_label_from_link(link: dict) -> str:
    s = link.get("Skill")
    if isinstance(s, dict):
        return s.get("MasterLabel") or s.get("DeveloperName") or "(sem nome)"
    return link.get("Skill.MasterLabel") or link.get("Skill.DeveloperName") or "(sem nome)"

def resolve_service_resource(instance_url, headers, identifier: str) -> dict:
    # Id direto
    if identifier.startswith("0Hn") and len(identifier) in (15, 18):
        q = f"""
            SELECT Id, Name, IsActive
            FROM ServiceResource
            WHERE Id = '{identifier}'
            LIMIT 1
        """
        recs = soql(instance_url, headers, q)
        if not recs:
            raise ValueError(f"ServiceResource não encontrado para Id={identifier}")
        r = recs[0]
        return {"id": r["Id"], "name": r.get("Name") or identifier, "is_active": bool(r.get("IsActive"))}

    safe = identifier.replace("'", "\\'")
    q = f"""
        SELECT Id, Name, IsActive
        FROM ServiceResource
        WHERE Name = '{safe}'
        ORDER BY LastModifiedDate DESC
        LIMIT 10
    """
    recs = soql(instance_url, headers, q)

    if not recs:
        # fallback LIKE
        q2 = f"""
            SELECT Id, Name, IsActive
            FROM ServiceResource
            WHERE Name LIKE '%{safe}%'
            ORDER BY LastModifiedDate DESC
            LIMIT 10
        """
        recs2 = soql(instance_url, headers, q2)
        if not recs2:
            raise ValueError(f"Nenhum técnico encontrado com: {identifier}")

        if len(recs2) > 1:
            ids = ", ".join([r.get("Id") for r in recs2 if r.get("Id")])
            raise ValueError(f"Nome ambíguo (LIKE). Use o Id 0Hn... | encontrados: {ids}")

        r = recs2[0]
        return {"id": r["Id"], "name": r.get("Name") or identifier, "is_active": bool(r.get("IsActive"))}

    if len(recs) > 1:
        ids = ", ".join([r.get("Id") for r in recs if r.get("Id")])
        raise ValueError(f"Nome duplicado. Use o Id 0Hn... | encontrados: {ids}")

    r = recs[0]
    return {"id": r["Id"], "name": r.get("Name") or identifier, "is_active": bool(r.get("IsActive"))}

def escape_soql(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")

def resolve_service_resource_by_email(instance_url, headers, email: str) -> Optional[dict]:
    safe_email = escape_soql(email.strip())
    if not safe_email:
        return None

    # Primeiro tenta localizar usuário pelo e-mail e depois o ServiceResource.
    q_user = f"""
        SELECT Id, Name, Email
        FROM User
        WHERE Email = '{safe_email}'
        LIMIT 10
    """
    users = soql(instance_url, headers, q_user)
    if not users:
        return None

    candidates = []
    for user in users:
        user_id = user.get("Id")
        if not user_id:
            continue
        q_sr = f"""
            SELECT Id, Name, IsActive, RelatedRecordId
            FROM ServiceResource
            WHERE RelatedRecordId = '{user_id}'
            ORDER BY LastModifiedDate DESC
            LIMIT 10
        """
        srs = soql(instance_url, headers, q_sr)
        for sr in srs:
            sr_id = sr.get("Id")
            if not sr_id:
                continue
            candidates.append(
                {
                    "id": sr_id,
                    "name": sr.get("Name") or email,
                    "is_active": bool(sr.get("IsActive")),
                    "email": user.get("Email") or email,
                }
            )

    if not candidates:
        return None

    unique_by_id = {c["id"]: c for c in candidates}
    unique_candidates = list(unique_by_id.values())
    if len(unique_candidates) > 1:
        ids = ", ".join([c["id"] for c in unique_candidates])
        raise ValueError(f"E-mail ambíguo: mais de um técnico encontrado ({ids})")

    return unique_candidates[0]

def get_group_skill_ids(instance_url, headers, group_name: str):
    if group_name not in GROUPS_MAP:
        raise ValueError(f"Grupo inválido: {group_name}")
    all_skills = list_all_skills(instance_url, headers, limit=2000)
    label_to_id = build_label_to_id(all_skills)
    groups_resolved, missing = build_groups_resolved(label_to_id)
    group_skills = groups_resolved.get(group_name, [])
    if not group_skills:
        missing_group = ", ".join(missing.get(group_name, []))
        raise ValueError(
            f"Nenhuma skill encontrada para o grupo '{group_name}'. "
            f"Verifique MasterLabel. Faltantes: {missing_group}"
        )
    return group_skills, missing.get(group_name, [])

def add_group_to_technician(instance_url, headers, sr_id: str, group_name: str, skill_level=None) -> bool:
    group_skills, _ = get_group_skill_ids(instance_url, headers, group_name)
    desired_ids = {s["id"] for s in group_skills}
    current_links = list_current_skill_links(instance_url, headers, sr_id)
    current_ids = {l.get("SkillId") for l in current_links if l.get("SkillId")}
    to_add = sorted(desired_ids - current_ids)
    for skill_id in to_add:
        create_service_resource_skill(instance_url, headers, sr_id, skill_id, skill_level=skill_level)
    return True

def remove_group_from_technician(instance_url, headers, sr_id: str, group_name: str) -> bool:
    group_skills, _ = get_group_skill_ids(instance_url, headers, group_name)
    desired_ids = {s["id"] for s in group_skills}
    current_links = list_current_skill_links(instance_url, headers, sr_id)
    current_by_skillid = {l.get("SkillId"): l.get("Id") for l in current_links if l.get("SkillId") and l.get("Id")}
    to_remove = sorted(desired_ids.intersection(set(current_by_skillid.keys())))
    for skill_id in to_remove:
        delete_service_resource_skill(instance_url, headers, current_by_skillid[skill_id])
    return True

def consult_technician(instance_url, headers, sr_id: str):
    current_links = list_current_skill_links(instance_url, headers, sr_id)
    current_skill_ids = {l.get("SkillId") for l in current_links if l.get("SkillId")}
    current_skill_labels = sorted({get_skill_label_from_link(l) for l in current_links})

    all_skills = list_all_skills(instance_url, headers, limit=2000)
    label_to_id = build_label_to_id(all_skills)
    groups_resolved, _ = build_groups_resolved(label_to_id)

    groups_status = []
    for group_name in GROUP_ORDER:
        group_ids = {s["id"] for s in groups_resolved.get(group_name, [])}
        if not group_ids:
            groups_status.append(
                {
                    "grupo": group_name,
                    "completo": False,
                    "skills_encontradas": 0,
                    "skills_total": 0,
                }
            )
            continue
        found = len(group_ids.intersection(current_skill_ids))
        groups_status.append(
            {
                "grupo": group_name,
                "completo": found == len(group_ids),
                "skills_encontradas": found,
                "skills_total": len(group_ids),
            }
        )

    return {
        "skills": current_skill_labels,
        "grupos": groups_status,
    }

def list_current_skill_links(instance_url, headers, sr_id: str):
    q = f"""
        SELECT Id, SkillId, Skill.MasterLabel, Skill.DeveloperName
        FROM ServiceResourceSkill
        WHERE ServiceResourceId = '{sr_id}'
        ORDER BY Skill.MasterLabel
    """
    return soql(instance_url, headers, q)

def patch_activate_service_resource(instance_url, headers, sr_id: str):
    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/ServiceResource/{sr_id}"
    payload = {"IsActive": True}
    r = requests.patch(url, headers={**headers, "Content-Type": "application/json"}, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Não consegui ativar ({r.status_code}): {r.text}")

def delete_service_resource_skill(instance_url, headers, link_id: str):
    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/ServiceResourceSkill/{link_id}"
    r = requests.delete(url, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Falha ao remover (link {link_id}) ({r.status_code}): {r.text}")

def create_service_resource_skill(instance_url, headers, sr_id: str, skill_id: str, skill_level=None):
    url = f"{instance_url}/services/data/{API_VERSION}/sobjects/ServiceResourceSkill"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = {
        "ServiceResourceId": sr_id,
        "SkillId": skill_id,
        "EffectiveStartDate": now_iso,
    }
    if skill_level is not None:
        payload["SkillLevel"] = int(skill_level)

    r = requests.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Falha ao adicionar skill ({r.status_code}): {r.text}")
    return r.json().get("id")


# =========================
# UI / INPUT
# =========================
def ask(prompt: str) -> str:
    return input(prompt).strip()

def read_identifiers_from_file(path: str) -> list[str]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out

def choose_group_interactive(groups_resolved, missing, color=True) -> str:
    print("\n" + bold("GRUPOS DISPONÍVEIS (SEU MAPA):", color))
    for i, g in enumerate(GROUP_ORDER, 1):
        ok_count = len(groups_resolved.get(g, []))
        miss_count = len(missing.get(g, []))
        extra = ""
        if miss_count:
            extra = warn(f"  (⚠ {miss_count} skill(s) do mapa NÃO existem na org)", color)
        print(f" {i}) {bold(g, color)} -> {ok_count} aplicável(is){extra}")

    v = ask("\nEscolha o grupo (número ou nome): ")
    if not v:
        return ""
    if v.isdigit():
        idx = int(v)
        if 1 <= idx <= len(GROUP_ORDER):
            return GROUP_ORDER[idx - 1]
        return ""
    v_norm = v.strip().lower()
    for g in GROUP_ORDER:
        if g.lower() == v_norm:
            return g
    return ""

def choose_mode(color=True) -> str:
    print("\n" + bold("Como tratar as skills atuais?", color))
    print(" 1) NÃO remover nada (só adiciona o que faltar do grupo)")
    print(" 2) Remover TODAS as skills atuais e deixar SOMENTE o grupo")
    print(" 3) Remover APENAS skills que NÃO fazem parte do grupo")
    m = ask("Escolha 1, 2 ou 3 [1]: ")
    return (m.strip() or "1")

def choose_subset_once_if_enabled(group_name: str, resolved_list: list[dict], enable: bool, color=True) -> list[dict]:
    """
    Se enable=False: retorna TODAS as skills do grupo (resolved_list).
    Se enable=True: deixa escolher A ou 1,2,5.
    """
    if not resolved_list:
        return []

    if not enable:
        # aplica tudo sem perguntar
        print("\n" + bold(f"SKILLS DO GRUPO '{group_name}' (serão aplicadas):", color))
        for s in resolved_list:
            print("  - " + warn(s["label"], color))
        return resolved_list

    print("\n" + bold(f"SKILLS DO GRUPO '{group_name}' (você pode escolher um subconjunto):", color))
    for i, s in enumerate(resolved_list, 1):
        print(f" {i:02d}) {s['label']}")

    v = ask("\nDigite 'A' para aplicar TODAS, ou números (ex: 1,2,5): ").strip().lower()
    if not v or v == "a":
        return resolved_list

    idxs = set()
    for part in v.replace(" ", "").split(","):
        if part.isdigit():
            idxs.add(int(part))

    chosen = []
    for i, s in enumerate(resolved_list, 1):
        if i in idxs:
            chosen.append(s)

    return chosen

def listar_grupos(sem_cor=False):
    color = not sem_cor
    instance_url, headers = sf_login_or_die()

    all_skills = list_all_skills(instance_url, headers, limit=2000)
    label_to_id = build_label_to_id(all_skills)
    groups_resolved, missing = build_groups_resolved(label_to_id)

    print("\n" + bold("GRUPOS DISPONÍVEIS (SEU MAPA):", color) + "\n")
    for g in GROUP_ORDER:
        print(bold(f"== {g} ==", color))
        # sempre mostra o que existe no seu mapa (em ordem)
        for label in GROUPS_MAP.get(g, []):
            sid = label_to_id.get(label)
            if sid:
                print("  - " + ok(f"{label} (SkillId={sid})", color))
            else:
                print("  - " + warn(f"{label} (⚠ não encontrada na org)", color))
        print()


# =========================
# PLANEJAMENTO / EXECUÇÃO
# =========================
def plan_one(instance_url, headers, identifier: str, ativar_inativo: bool):
    try:
        sr = resolve_service_resource(instance_url, headers, identifier)
    except Exception as e:
        return {"status": "ERROR", "identifier": identifier, "msg": str(e)}

    sr_id, sr_name, is_active = sr["id"], sr["name"], sr["is_active"]

    if not is_active and ativar_inativo:
        try:
            patch_activate_service_resource(instance_url, headers, sr_id)
            sr = resolve_service_resource(instance_url, headers, sr_id)
            is_active = sr["is_active"]
        except Exception as e:
            return {"status": "SKIP", "identifier": identifier, "sr_id": sr_id, "sr_name": sr_name, "msg": f"inativo e falhou ao ativar: {e}"}

    if not is_active:
        return {"status": "SKIP", "identifier": identifier, "sr_id": sr_id, "sr_name": sr_name, "msg": "técnico INATIVO (org bloqueia skill)"}

    current_links = list_current_skill_links(instance_url, headers, sr_id)
    current_by_skillid = {}
    current_ids = set()
    current_names = []

    for l in current_links:
        sid = l.get("SkillId")
        lid = l.get("Id")
        if sid and lid:
            current_by_skillid[sid] = lid
            current_ids.add(sid)
        current_names.append(get_skill_label_from_link(l))

    return {
        "status": "OK",
        "identifier": identifier,
        "sr_id": sr_id,
        "sr_name": sr_name,
        "current_links": current_links,
        "current_by_skillid": current_by_skillid,
        "current_ids": current_ids,
        "current_names": current_names,
    }

def compute_changes(mode: str, current_ids: set, desired_ids: set):
    if mode == "1":
        to_remove = set()
    elif mode == "2":
        to_remove = set(current_ids)
    else:
        to_remove = set(current_ids - desired_ids)
    to_add = set(desired_ids - current_ids)
    return to_remove, to_add

def print_preview(plan, group_name, mode, desired_id_to_label, color=True):
    if plan["status"] == "ERROR":
        print(err(f"\n[ERRO] {plan['identifier']} -> {plan['msg']}", color))
        return
    if plan["status"] == "SKIP":
        print(warn(f"\n[SKIP] {plan.get('sr_name', plan['identifier'])} | {plan.get('sr_id','')} -> {plan['msg']}", color))
        return

    sr_name = plan["sr_name"]
    sr_id = plan["sr_id"]

    desired_ids = set(desired_id_to_label.keys())
    to_remove, to_add = compute_changes(mode, plan["current_ids"], desired_ids)

    # map skillId->nome atual (pra remover com nome)
    current_skillid_to_name = {}
    for l in plan["current_links"]:
        sid = l.get("SkillId")
        if sid:
            current_skillid_to_name[sid] = get_skill_label_from_link(l)

    mode_txt = {
        "1": "MODO 1 (não remove, só adiciona)",
        "2": "MODO 2 (remove tudo e deixa só o grupo)",
        "3": "MODO 3 (remove só o que não é do grupo)",
    }.get(mode, f"MODO {mode}")

    title = f"👷 {sr_name}  {badge('OK', 'ok', color)}"
    lines = [
        f"🆔 ServiceResourceId: {sr_id}",
        f"📦 Grupo: {group_name}",
        f"⚙️  {mode_txt}",
    ]
    box(title, lines, enabled=color, accent_code="96")
    hr(enabled=color)

    print(bold(f"Skills atuais ({len(plan['current_names'])}):", color))
    if not plan["current_names"]:
        print("  - (nenhuma)")
    else:
        for n in plan["current_names"]:
            print("  - " + ok(n, color))

    print(bold(f"\nVai remover ({len(to_remove)}):", color))
    if not to_remove:
        print("  - (nada)")
    else:
        for sid in sorted(to_remove):
            print("  - " + err(current_skillid_to_name.get(sid, sid), color))

    print(bold(f"\nVai adicionar ({len(to_add)}):", color))
    if not to_add:
        print("  - (nada)")
    else:
        for sid in sorted(to_add):
            print("  - " + warn(desired_id_to_label.get(sid, sid), color))

def execute(plan, instance_url, headers, mode, desired_id_to_label, skill_level):
    if plan["status"] != "OK":
        return {"removed_ok": 0, "removed_fail": 0, "added_ok": 0, "added_fail": 0}

    desired_ids = set(desired_id_to_label.keys())
    to_remove, to_add = compute_changes(mode, plan["current_ids"], desired_ids)

    removed_ok = removed_fail = 0
    added_ok = added_fail = 0

    for sid in sorted(to_remove):
        link_id = plan["current_by_skillid"].get(sid)
        if not link_id:
            continue
        try:
            delete_service_resource_skill(instance_url, headers, link_id)
            removed_ok += 1
        except Exception:
            removed_fail += 1

    for sid in sorted(to_add):
        try:
            create_service_resource_skill(instance_url, headers, plan["sr_id"], sid, skill_level=skill_level)
            added_ok += 1
        except Exception:
            added_fail += 1

    return {"removed_ok": removed_ok, "removed_fail": removed_fail, "added_ok": added_ok, "added_fail": added_fail}

def create_api_app():
    app = Flask(__name__)

    @app.after_request
    def add_cors_headers(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

    @app.route("/api/<path:_path>", methods=["OPTIONS"])
    def api_options(_path):
        return ("", 204)

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/tecnico/existe")
    def tecnico_existe():
        body = request.get_json(silent=True) or {}
        email = (body.get("email") or "").strip()
        if not email:
            return jsonify({"result": False, "error": "Campo 'email' é obrigatório"}), 400
        try:
            instance_url, headers = sf_login_for_api()
            sr = resolve_service_resource_by_email(instance_url, headers, email)
            return jsonify({"result": bool(sr)})
        except Exception as e:
            return jsonify({"result": False, "error": str(e)}), 500

    @app.post("/api/grupo/adicionar")
    def grupo_adicionar():
        body = request.get_json(silent=True) or {}
        email = (body.get("email") or "").strip()
        grupo = (body.get("grupo") or "").strip()
        skill_level = body.get("skill_level")
        if not email or not grupo:
            return jsonify({"result": False, "error": "Campos 'email' e 'grupo' são obrigatórios"}), 400
        try:
            instance_url, headers = sf_login_for_api()
            sr = resolve_service_resource_by_email(instance_url, headers, email)
            if not sr:
                return jsonify({"result": False, "error": "Técnico não encontrado"}), 404
            add_group_to_technician(instance_url, headers, sr["id"], grupo, skill_level=skill_level)
            return jsonify({"result": True})
        except Exception as e:
            return jsonify({"result": False, "error": str(e)}), 500

    @app.post("/api/grupo/remover")
    def grupo_remover():
        body = request.get_json(silent=True) or {}
        email = (body.get("email") or "").strip()
        grupo = (body.get("grupo") or "").strip()
        if not email or not grupo:
            return jsonify({"result": False, "error": "Campos 'email' e 'grupo' são obrigatórios"}), 400
        try:
            instance_url, headers = sf_login_for_api()
            sr = resolve_service_resource_by_email(instance_url, headers, email)
            if not sr:
                return jsonify({"result": False, "error": "Técnico não encontrado"}), 404
            remove_group_from_technician(instance_url, headers, sr["id"], grupo)
            return jsonify({"result": True})
        except Exception as e:
            return jsonify({"result": False, "error": str(e)}), 500

    @app.get("/api/tecnico/consultar")
    def tecnico_consultar():
        email = (request.args.get("email") or "").strip()
        if not email:
            return jsonify({"result": False, "error": "Query param 'email' é obrigatório"}), 400
        try:
            instance_url, headers = sf_login_for_api()
            sr = resolve_service_resource_by_email(instance_url, headers, email)
            if not sr:
                return jsonify({"result": False, "found": False})
            consulta = consult_technician(instance_url, headers, sr["id"])
            skills_nomes = consulta.get("skills", [])
            return jsonify(
                {
                    "result": True,
                    "found": True,
                    "tecnico": {
                        "id": sr["id"],
                        "nome": sr["name"],
                        "email": sr.get("email") or email,
                        "ativo": sr["is_active"],
                    },
                    "skills": skills_nomes,
                }
            )
        except Exception as e:
            return jsonify({"result": False, "error": str(e)}), 500

    return app

def run_rest_api(host: str, port: int):
    app = create_api_app()
    app.run(host=host, port=port, debug=False)


def main(args):
    color = not args.sem_cor

    big_header(
        app_name="ENSURE MANUTENÇÃO SKILL",
        subtitle="Aplicador de Skills (ServiceResourceSkill) - Desktop Salesforce",
        enabled=color,
    )

    # montar lista de técnicos
    identifiers = []
    if args.id_ou_nome:
        identifiers.append(args.id_ou_nome)
    if args.ids_ou_nomes:
        identifiers.extend(args.ids_ou_nomes)
    if args.arquivo:
        identifiers.extend(read_identifiers_from_file(args.arquivo))

    # dedup mantendo ordem
    seen = set()
    dedup = []
    for x in identifiers:
        x = x.strip()
        if not x or x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    identifiers = dedup

    if not identifiers:
        raise SystemExit("❌ Nenhum técnico informado. Use --id-ou-nome, --ids-ou-nomes ou --arquivo.")

    instance_url, headers = sf_login_or_die()

    # carrega skills 1x (pra resolver MasterLabel -> Id)
    all_skills = list_all_skills(instance_url, headers, limit=2000)
    label_to_id = build_label_to_id(all_skills)
    groups_resolved, missing = build_groups_resolved(label_to_id)

    # resolve grupo
    group_name = args.grupo
    if group_name:
        # aceita número
        if group_name.isdigit():
            idx = int(group_name)
            if 1 <= idx <= len(GROUP_ORDER):
                group_name = GROUP_ORDER[idx - 1]
        if group_name not in GROUPS_MAP:
            raise SystemExit("❌ Grupo inválido. Use --listar-grupos para ver os válidos.")
    else:
        group_name = choose_group_interactive(groups_resolved, missing, color=color)
        if not group_name:
            raise SystemExit("❌ Grupo inválido/vazio.")

    # lista do grupo vinda do SEU MAPA (já resolvida pra ids que existem na org)
    resolved_list = groups_resolved.get(group_name, [])

    # mostra também as do mapa que não bateram com MasterLabel da org
    if missing.get(group_name):
        print("\n" + warn("⚠ Atenção: essas skills estão no seu GROUPS_MAP, mas NÃO existem na org (MasterLabel diferente).", color))
        for m in missing[group_name]:
            print("  - " + warn(m, color))

    chosen_resolved = choose_subset_once_if_enabled(
        group_name=group_name,
        resolved_list=resolved_list,
        enable=args.selecionar_skills,
        color=color
    )
    if not chosen_resolved:
        raise SystemExit("❌ Nenhuma skill aplicável encontrada para esse grupo (todas faltando na org?).")

    desired_id_to_label = {x["id"]: x["label"] for x in chosen_resolved}

    # modo
    mode = args.modo or choose_mode(color=color)
    if mode not in ("1", "2", "3"):
        raise SystemExit("❌ Modo inválido. Use 1, 2 ou 3.")

    print("\n" + bold(f"📌 Ação: aplicar '{group_name}' em {len(identifiers)} técnico(s).", color))
    print(bold("Gerando prévia por técnico...", color))

    plans = []
    for ident in identifiers:
        p = plan_one(instance_url, headers, ident, ativar_inativo=args.ativar_inativo)
        plans.append(p)
        print_preview(p, group_name, mode, desired_id_to_label, color=color)

    ok_plans = [p for p in plans if p["status"] == "OK"]
    skip_plans = [p for p in plans if p["status"] == "SKIP"]
    err_plans = [p for p in plans if p["status"] == "ERROR"]

    hr(enabled=color)
    box(
        "📊 RESUMO GERAL",
        [
            f"{badge('OK', 'ok', color)} elegíveis: {len(ok_plans)}",
            f"{badge('SKIP', 'warn', color)}: {len(skip_plans)}",
            f"{badge('ERRO', 'err', color)}: {len(err_plans)}",
            f"Dry-run: {'SIM' if args.dry_run else 'NÃO'}",
        ],
        enabled=color,
        accent_code="95",
    )

    if args.dry_run:
        print(warn("\n[DRY-RUN] Nada foi alterado no Salesforce (só prévia).", color))
        return

    if not ok_plans:
        print(warn("\nNada para aplicar (ninguém elegível).", color))
        return

    confirm = ask(f"\nDigite SIM para EXECUTAR em {len(ok_plans)} técnico(s): ").strip().lower()
    if confirm != "sim":
        print(err("❌ Cancelado.", color))
        return

    total_removed_ok = total_removed_fail = 0
    total_added_ok = total_added_fail = 0

    print("\n" + bold("🚀 Executando...", color))
    for p in ok_plans:
        r = execute(p, instance_url, headers, mode, desired_id_to_label, args.skill_level)
        total_removed_ok += r["removed_ok"]
        total_removed_fail += r["removed_fail"]
        total_added_ok += r["added_ok"]
        total_added_fail += r["added_fail"]

        print(ok(
            f"✅ {p['sr_name']} ({p['sr_id']}) | removidas ok={r['removed_ok']} falhas={r['removed_fail']} | adicionadas ok={r['added_ok']} falhas={r['added_fail']}",
            color
        ))
    hr(enabled=color)
    box(
        "🏁 FINAL",
        [
            f"Remoções: ok={total_removed_ok} | falhas={total_removed_fail}",
            f"Adições:  ok={total_added_ok} | falhas={total_added_fail}",
        ],
        enabled=color,
        accent_code="95",
    )
    print(ok("\n✅ Concluído.", color))
    print("\n" + bold(ok("🔥 TA MUITO FODA. ✔️", color), color))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", action="store_true", help="Inicia a API REST")
    ap.add_argument("--host", default="0.0.0.0", help="Host da API REST")
    ap.add_argument("--port", type=int, default=5000, help="Porta da API REST")

    ap.add_argument("--id-ou-nome", required=False, help="Um ServiceResource Id (0Hn...) ou Nome do técnico")
    ap.add_argument("--ids-ou-nomes", nargs="+", required=False, help="Vários nomes/IDs (separados por espaço)")
    ap.add_argument("--arquivo", required=False, help="Arquivo .txt com 1 nome/ID por linha")

    ap.add_argument("--grupo", required=False, help="Grupo (nome ou número). Ex: 'Retirada' ou '6'")
    ap.add_argument("--modo", required=False, help="1, 2 ou 3 (remoção). Se não passar, pergunta.")
    ap.add_argument("--skill-level", default=None, help="Opcional: SkillLevel (se sua org exigir)")

    ap.add_argument("--ativar-inativo", action="store_true", help="Tenta ativar técnico se estiver inativo (senão, pula)")
    ap.add_argument("--dry-run", action="store_true", help="Só mostra a prévia, não executa nada")

    ap.add_argument("--sem-cor", action="store_true", help="Desativa cores no terminal")
    ap.add_argument("--listar-grupos", action="store_true", help="Só lista os grupos e sai")
    ap.add_argument("--selecionar-skills", action="store_true", help="Permite escolher subconjunto dentro do grupo (senão aplica todas)")

    args = ap.parse_args()

    if args.api:
        run_rest_api(args.host, args.port)
        raise SystemExit(0)

    if args.listar_grupos:
        listar_grupos(sem_cor=args.sem_cor)
        raise SystemExit(0)

    main(args)



# ============================================================
# ✅ MANUAL DE COMANDOS (Windows / CMD) — ensure_manutencao_skill.py
# ============================================================
#
# Este script aplica um "GRUPO" de skills (definido no GROUPS_MAP)
# em 1 ou vários técnicos (ServiceResource), com 3 modos de remoção.
#
# -------------------------
# 0) REGRAS IMPORTANTES
# -------------------------
# - Se o técnico estiver INATIVO, a org pode bloquear alterar skills.
#   → Você pode usar --ativar-inativo para tentar ativar automaticamente.
# - Se você usar --dry-run: NÃO muda nada. Só mostra a prévia.
# - Sem --grupo e sem --modo, ele pergunta interativamente.
# - Mesmo passando --grupo, o script pode perguntar "A" ou "1,2,3" para
#   escolher o SUBSET do grupo (aplicar todas ou só algumas).
# - No final (sem dry-run), ele pede confirmação digitando "SIM".
#
# -------------------------
# 1) LISTAR GRUPOS DISPONÍVEIS
# -------------------------
# Mostra os grupos do seu GROUPS_MAP e quais skills vão ser aplicadas.
#
# (Apenas listar e sair)
# python ensure_manutencao_skill.py --listar-grupos
#
# (Listar sem cores — útil em terminais ruins/prints)
# python ensure_manutencao_skill.py --listar-grupos --sem-cor
#
# -------------------------
# 2) RODAR EM 1 TÉCNICO (ID ou Nome)
# -------------------------
# (Por Nome — se tiver espaço, SEMPRE use aspas)
# python ensure_manutencao_skill.py --id-ou-nome "DOUGLAS RODRIGO LUCIO MAIA"
#
# (Por Id 0Hn... — mais seguro, evita ambiguidade)
# python ensure_manutencao_skill.py --id-ou-nome "0HnV20000003W1lKAE"
#
# -------------------------
# 3) RODAR EM VÁRIOS TÉCNICOS (lista no comando)
# -------------------------
# Você pode passar vários nomes/ids de uma vez:
#
# python ensure_manutencao_skill.py --ids-ou-nomes \
#   "DOUGLAS RODRIGO LUCIO MAIA" "0HnV20000003W1lKAE" "OUTRO NOME"
#
# -------------------------
# 4) RODAR EM VÁRIOS TÉCNICOS (arquivo .txt)
# -------------------------
# Crie um arquivo tecnicos.txt com 1 por linha (nome ou 0Hn...):
#
#   DOUGLAS RODRIGO LUCIO MAIA
#   0HnV20000003W1lKAE
#   MAICON SANTOS MOREIRA DOMINGOS
#
# Linhas vazias e linhas começando com # são ignoradas.
#
# Rodar:
# python ensure_manutencao_skill.py --arquivo tecnicos.txt
#
# -------------------------
# 5) ESCOLHER GRUPO SEM PERGUNTAR (não-interativo)
# -------------------------
# Em vez de digitar o grupo na hora, você passa no comando:
#
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada"
#
# Também aceita número (ordem do GROUP_ORDER):
# ex.: se "Retirada" for o 6º:
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo 6
#
# -------------------------
# 6) MODOS (o mais importante)
# -------------------------
# --modo 1  => NÃO remove nada. Só ADICIONA o que faltar do grupo.
# --modo 2  => Remove TODAS as skills atuais e deixa SOMENTE o grupo.
# --modo 3  => Remove APENAS as skills que NÃO estão no grupo.
#
# Exemplos:
#
# (Modo 1) Só adicionar Retirada (não remove nada)
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 1
#
# (Modo 2) “Reset total”: remove tudo e deixa só Retirada
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 2
#
# (Modo 3) Alinhar ao grupo: remove o que não é Retirada e completa o que falta
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3
#
# -------------------------
# 7) TESTAR SEM MUDAR NADA (DRY-RUN)
# -------------------------
# Mostra a prévia completa (skills atuais / vai remover / vai adicionar),
# mas NÃO executa nada.
#
# (Ex: só adicionar — modo 1 — SEM alterar nada)
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 1 --dry-run
#
# (Ex: remover o que não é do grupo — modo 3 — SEM alterar nada)
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3 --dry-run
#
# -------------------------
# 8) TENTAR ATIVAR TÉCNICOS INATIVOS
# -------------------------
# Se a org impedir mexer em skills de técnico inativo, use:
#
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3 --ativar-inativo
#
# OBS: Se a org bloquear ativação, o técnico vai cair em SKIP.
#
# -------------------------
# 9) SEM COR (prints mais limpos)
# -------------------------
# Remove ANSI colors do terminal:
#
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3 --dry-run --sem-cor
#
# -------------------------
# 10) SKILL LEVEL (raro)
# -------------------------
# Algumas orgs exigem SkillLevel ao criar ServiceResourceSkill.
# Se precisar, passe:
#
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3 --skill-level 3
#
# -------------------------
# 11) FLUXO "100% SEM PERGUNTAS" (exceto subset)
# -------------------------
# Para automatizar ao máximo:
# - passe --grupo e --modo
# - use --dry-run para validar
# - depois rode sem dry-run para executar
#
# Ex:
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3 --dry-run
# python ensure_manutencao_skill.py --arquivo tecnicos.txt --grupo "Retirada" --modo 3
#
# -------------------------
# 12) SUBSET DO GRUPO (quando você quer só algumas)
# -------------------------
# Quando ele listar:
#   SKILLS DO GRUPO 'Retirada' ...
#   01) Chip
#   02) MotoDesk
#   ...
#
# Você digita:
# - A        => aplica todas do grupo
# - 1,3,6    => aplica só as selecionadas
#
# OBS: isso é 1 vez e vale para TODOS os técnicos do arquivo.
#
# ============================================================

