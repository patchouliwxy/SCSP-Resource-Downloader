"""Version-independent browsing rules. No network requests or index mutations.

Categories describe catalog names, not a verification of animation bindings or
editable Unity scenes. Unrecognized files retain an explicit fallback category.
"""
import re

# id: (label, browsing scope)
CATEGORY_INFO = {
    'head': ('角色头部', 'model'), 'hair': ('发型', 'model'),
    'dress': ('服装', 'model'), 'accessory': ('饰品', 'model'),
    'dance': ('歌曲主舞蹈', 'motion'),
    'performance': ('歌曲演出片段', 'motion'),
    'story_motion': ('剧情片段动作', 'motion'),
    'character_motion': ('角色通用动作', 'motion'),
    'lesson_motion': ('课程与练习动作', 'motion'),
    'outfit_motion': ('换装与服装适配动作', 'motion'),
    'sd_motion': ('SD 角色动作', 'motion'),
    'expression': ('表情与口型', 'motion'),
    'root_motion': ('走位与根运动', 'motion'),
    'camera_motion': ('镜头数据与动画', 'motion'),
    'stage_animation': ('舞台与场景动画', 'motion'),
    'ui_animation': ('界面与抽卡动画', 'motion'),
    'animation': ('其他动画（用途未确认）', 'motion'),
    'timeline': ('演出时间线', 'motion'),
    'scene_mv': ('歌曲 MV 场景', 'scene'),
    'scene_story': ('剧情场景', 'scene'),
    'scene_lesson': ('课程与练习场景', 'scene'),
    'scene_diorama': ('Diorama 拍照背景', 'scene'),
    'scene_outfit': ('换装与试衣场景', 'scene'),
    'scene_system': ('系统与功能场景', 'scene'),
    'scene_other': ('其他场景（用途未确认）', 'scene'),
    'stage_model': ('舞台模型部件', 'scene'),
    'background_model': ('背景模型部件', 'scene'),
    'audio_song': ('歌曲主音频', 'audio'),
    'audio_character': ('歌曲角色音轨', 'audio'),
    'audio_instrumental': ('歌曲伴奏 / BGM', 'audio'),
    'audio_runway': ('换装 / 走秀音乐', 'audio'),
    'audio_mv': ('MV 配套音频', 'audio'),
    'audio_story': ('剧情与对白音频', 'audio'),
    'audio_cutscene': ('演出片段音频', 'audio'),
    'audio_bgm': ('背景音乐', 'audio'),
    'audio_ambience': ('环境声', 'audio'),
    'audio_sfx_story': ('剧情音效', 'audio'),
    'audio_sfx_gasha': ('抽卡音效', 'audio'),
    'audio_sfx': ('系统与其他音效', 'audio'),
    'audio_event': ('活动音频（inst_event）', 'audio'),
    'audio': ('其他音频（用途未确认）', 'audio'),
    'texture': ('贴图', 'other'),
    'other': ('其他资源', 'other'),
}
CATEGORIES = {key: label for key, (label, _) in CATEGORY_INFO.items()}
SYSTEM_SCENES = {'3d', 'ar', 'gashaeffect', 'lessonaudition', 'liveresult',
                 'mvsequencer', 'ourstreamliveviewing', 'spawncharacteroutgameview'}


def classify_resource(entry, song_codes=None):
    """Return category and auditable rule. song_codes comes from this index."""
    name = entry['name'].rsplit('/', 1)[-1].lower()
    kind = entry['type'].lower()
    stem = name.rsplit('.', 1)[0]
    def result(category, rule):
        return dict(category=category, scope=CATEGORY_INFO[category][1], category_basis=rule)
    if kind == 'unity':
        if re.match(r'^s\d{2}_', stem) or stem == 'scenario':
            return result('scene_story', '场景名称 sNN_ / scenario')
        if 'lesson' in stem:
            return result('scene_lesson', '场景名称含 lesson')
        if stem.startswith('dioramabackground_'):
            return result('scene_diorama', '场景名称 dioramabackground_')
        if stem in ('costumechange', 'fittingroom') or stem.startswith('900_dresso'):
            return result('scene_outfit', '场景名称 costumechange / fittingroom / 900_dresso')
        if song_codes is not None and stem in song_codes:
            return result('scene_mv', '同版本已识别主舞蹈文件族存在同代码场景')
        if stem in SYSTEM_SCENES:
            return result('scene_system', '已识别系统场景名称')
        return result('scene_other', '.unity 文件类型；用途尚未确认')
    for prefix, category in (('m_head_', 'head'), ('m_hair_', 'hair'),
                             ('m_dress_', 'dress'), ('m_acce_', 'accessory')):
        if name.startswith(prefix) and kind == 'prefab':
            return result(category, '模型 prefab 名称前缀 ' + prefix)
    if kind in ('prefab', 'fbx'):
        if re.match(r'^(?:stage_|m_stage_|mdl_lv_)', name):
            return result('stage_model', '舞台模型名称前缀；不等于完整场景')
        if re.match(r'^(?:bgmodel_|m_bgmodel_|bg_|office_)', name):
            return result('background_model', '背景模型名称前缀；不等于歌曲舞台')
    if kind == 'playable':
        return result('timeline', '.playable 时间线，非独立身体 AnimationClip')
    # Restrict semantic motion matching to motion containers, never textures/models.
    motion = kind == 'anim' or (kind == 'asset' and name.endswith(('_body.asset', '_root.asset')))
    if kind == 'json' and name.endswith(('_exp.json', '_mouth.json', '_eye.json')):
        return result('expression', '表情事件 JSON 文件后缀')
    if kind == 'json' and name.endswith('_camera.json'):
        return result('camera_motion', '相机 JSON 文件后缀')
    if kind == 'fbx' and name.endswith('_cameraanime.fbx'):
        return result('camera_motion', 'cameraanime 动画包名称；目录后缀不是导出格式证明')
    if motion:
        if name.endswith(('_root.asset', '_root.anim')):
            return result('root_motion', '独立 _root 曲线文件后缀')
        if (re.search(r'_(?:exp|facial)(?:_|\.)', name) or
                re.search(r'(?:face|mouth|eye)(?:anim|brow|close|smile)', name)):
            return result('expression', '面部 facial / exp / face 动画名称')
        if re.search(r'_(?:camerawork|cameraanime|camera_\d+)(?:_|\.)', name):
            return result('camera_motion', '明确相机 camerawork / cameraanime / camera_N 动画名')
        if 'lesson' in name:
            return result('lesson_motion', '动作名称含 lesson')
        if name.startswith('motsd_'):
            return result('sd_motion', '动作名称 motsd_ 前缀')
        if name.startswith(('motdrs_', 'admot_dress_', '900_dresso_', 'fasionshow_')):
            return result('outfit_motion', '换装/服装适配动作名称前缀')
        main = re.fullmatch(r'(\d{3}_[a-z0-9]+)(?:_\d{2})?(?:\.anim|_body\.asset)', name)
        if main and (song_codes is None or main[1] in song_codes):
            return result('dance', '主身体文件命名' + ('及同版本文件族' if song_codes is not None else '规则'))
        if re.match(r'^(?:mot_\d{3}[a-z0-9]+_|mota_\d{3}_)', name):
            return result('performance', '歌曲代码演出动作 mot_ / mota_ 前缀；非主舞蹈')
        if re.match(r'^s\d{2}_', name):
            return result('story_motion', '剧情片段 sNN_ 动作命名规则')
        if name.startswith('chara_initial_') or re.match(r'^motion\d{2}_', name):
            return result('character_motion', '角色 chara_initial_ / motionNN_ 动作命名')
        if name.startswith(('an_lv_', 'ef_adv_', 'an_bgmodel_', 'an_stage_')):
            return result('stage_animation', '场景动画 an_lv_ / ef_adv_ / an_bgmodel_ / an_stage_')
        if name.startswith(('an_gasha', 'gasha_', 'cmn_', 'live_ui_', 'produce_')) or re.search(r'(?:overlayview|dialogview|screenview)', name):
            return result('ui_animation', '界面/抽卡动画名称规则')
        return result('animation', '动画容器类型；未命中已知用途规则')
    if kind in ('acb', 'awb'):
        if stem == '900_dresso' or re.fullmatch(r'\d{3}_[a-z0-9]+_runway', stem):
            return result('audio_runway', '音频名称 900_dresso / 歌曲代码_runway')
        if re.fullmatch(r'\d{3}_[a-z0-9]+_\d{2}[a-z][a-z0-9]*', stem):
            return result('audio_character', '歌曲代码后带角色编号及名称；不保证包内仅有纯人声')
        if re.fullmatch(r'\d{3}_[a-z0-9]+_(?:bgm|inst)', stem):
            return result('audio_instrumental', '歌曲音频名称的 _bgm / _inst 后缀；按命名推断用途')
        if re.fullmatch(r'\d{3}_[a-z0-9]+_addcs', stem) or stem.startswith('cs_'):
            return result('audio_cutscene', '音频名称 cs_ 前缀 / 歌曲 _addcs 后缀；不假定仅为台词')
        if re.fullmatch(r'\d{3}_[a-z0-9]+', stem):
            return result('audio_song', '三位歌曲代码音频主包；包内可能包含多条音轨')
        if re.fullmatch(r'mv_\d{3}_[a-z0-9]+', stem):
            return result('audio_mv', 'MV 音频 mv_歌曲代码；具体内容以音轨为准')
        if re.match(r'^s\d{2}_', stem):
            return result('audio_story', '音频名称 sNN_ 剧情规则；NN 不是角色编号')
        if stem.startswith('bgm_'):
            return result('audio_bgm', '背景音乐 bgm_ 前缀')
        if stem in ('ambi', 'amb') or stem.startswith(('ambi_', 'amb_')):
            return result('audio_ambience', '环境声 ambi / amb 前缀')
        if stem == 'se_adv' or stem.startswith('se_adv_') or re.fullmatch(r'adv_foot\d*', stem):
            return result('audio_sfx_story', '剧情音效 se_adv / adv_foot 命名')
        if re.match(r'^se_(?:pgasha|gasha\d*)(?:_|$)', stem):
            return result('audio_sfx_gasha', '抽卡音效 se_pgasha / se_gasha 命名')
        if stem.startswith('se_'):
            return result('audio_sfx', '音效 se_ 前缀；具体系统见资源原名')
        if re.fullmatch(r'inst_event_\d+', stem):
            return result('audio_event', '活动音频 inst_event_N；未验证为歌曲伴奏')
        return result('audio', 'CRI 音频包类型；未命中已确认的名称族')
    if kind in ('png', 'tga', 'exr'):
        return result('texture', '贴图文件类型')
    return result('other', '未命中用途规则')


def character_hint(entry):
    name = entry['name'].rsplit('/', 1)[-1].lower()
    if entry['type'].lower() in ('acb', 'awb'):
        match = re.fullmatch(r'\d{3}_[a-z0-9]+_(\d{2})[a-z][a-z0-9]*\.(?:acb|awb)', name)
        return match[1] if match else ''
    for pattern in (r'm_(?:head|hair)_(\d{2})[_.]',
                    r'm_(?:dress|acce)_\d+_(\d{2})[a-z]',
                    r'motion(\d{2})_', r'(\d{2})_[a-z]+_facial_',
                    r's\d{2}_\d+_\d+_\d+_(\d{2})[a-z]+\.',
                    r'mot_\d{3}[a-z0-9]+_[a-z0-9]+_\d+_(\d{2})_\d+\.'):
        match = re.match(pattern, name)
        if match:
            return match[1]
    return ''
