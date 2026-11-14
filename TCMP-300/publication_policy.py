"""Public content rules; raw import data and model labels remain archival records."""
import ipaddress
import json
import re
from urllib.parse import urlsplit

BOTANICAL_HOSTS = {'www.iplant.cn', 'iplant.cn', 'api.gbif.org', 'www.gbif.org'}
UNRESOLVED = re.compile(r'待核实|待核验|待核对|待核查|等待核验|待复核|待审核|未核实|未核验|未核对|未核查|未审核|未人工审核|待人工|待专业|待药典|待2025|待编辑|尚无可靠|需核实|未经过(?:人工|专业)')
UNUSABLE_EVIDENCE = re.compile(r'旧版|歧义|冲突|尚未采用|DOUBTFUL|组合|待编辑|待专业|待药典|待2025|待药材', re.I)


def parsed(value, fallback):
    try:
        result = json.loads(value or '')
        return result if isinstance(result, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def public_url(value):
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme not in {'http', 'https'} or not host or url.username or url.password:
            return False
        if host == 'localhost' or host.endswith(('.local', '.localhost')):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return '.' in host
    except (TypeError, ValueError):
        return False


def source_links(text):
    return [url for url in re.findall(r'https?://[^\s<>"；，]+', text or '')
            if public_url(url.rstrip('。;,)）'))]


def article_is_public(row):
    return (row.get('status') == 'published' and not row.get('deleted_at')
            and row.get('review_status') == '已审核' and row.get('source_kind') == 'editorial'
            and bool(source_links(row.get('source_note', '')))
            and bool(row.get('body', '').strip())
            and not UNRESOLVED.search(' '.join(row.get(key, '') or '' for key in ('title', 'excerpt', 'body', 'source_note'))))


def botanical_evidence(row):
    """Use only current, directly sourced botanical values, never retired extractions."""
    index = {item.get('evidence_id'): item for item in parsed(row.get('字段证据JSON'), []) if isinstance(item, dict)}
    mapping = parsed(row.get('字段来源JSON'), {})
    review = parsed(row.get('字段核对状态JSON'), {})
    def binomial(value):
        match = re.match(r'^([A-Za-z-]+)\s+([a-z-]+)', value.strip())
        return tuple(part.casefold() for part in match.groups()) if match else None
    # Classification records pending cross-reference may only be used when their
    # name agrees with the independently stored botanical source, not merely a hit.
    source_name = binomial(row.get('植物智学名', ''))
    classified_name = binomial(row.get('规范学名', ''))
    classification_matches = bool(source_name and source_name == classified_name)
    result = {}
    for field, ids in mapping.items():
        if not isinstance(ids, list) or any(term in str(review.get(field, '')) for term in ('尚无可靠', '不适用')):
            continue
        items = []
        for evidence_id in ids:
            item = index.get(evidence_id)
            if not item or item.get('field') != field:
                continue
            url = item.get('url', '')
            if not public_url(url) or urlsplit(url).hostname not in BOTANICAL_HOSTS:
                continue
            value = str(item.get('value', '')).strip()
            if not value or UNRESOLVED.search(value) or UNUSABLE_EVIDENCE.search(str(item.get('status', ''))):
                continue
            if '待交叉核对' in str(item.get('status', '')) and not classification_matches:
                continue
            items.append(item)
        if items:
            result[field] = items
    return result


def botanical_value(evidence, field):
    return '；'.join(dict.fromkeys(str(item['value']).strip().strip('；;') for item in evidence.get(field, [])))


def plant_is_public(row, evidence=None):
    if not row or '冲突' in row.get('身份核对状态', ''):
        return False
    evidence = botanical_evidence(row) if evidence is None else evidence
    return bool(botanical_value(evidence, '规范中文名') and
                (botanical_value(evidence, '规范学名') or botanical_value(evidence, '植物智学名')))


def plant_image_is_public(row, evidence=None):
    # Candidate training images with unresolved identity/licensing are not website assets.
    return bool(row and plant_is_public(row, evidence) and row.get('封面图')
                and row.get('图片审核状态') == '已审核'
                and row.get('图片授权状态') in {'已授权', '开放许可'})
