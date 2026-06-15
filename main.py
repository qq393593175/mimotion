# -*- coding: utf8 -*-
import math
import traceback
from datetime import datetime
import pytz
import uuid
import json
import random
import re
import time
import os
from util.aes_help import encrypt_data, decrypt_data
import util.zepp_helper as zeppHelper
import util.push_util as push_util

# 步数状态文件路径
STEP_STATE_FILE = "step_state.json"

def get_int_value_default(_config, _key, default):
    _config.setdefault(_key, default)
    return int(_config.get(_key))

def get_min_max_by_time(hour=None, minute=None):
    if hour is None:
        hour = time_bj.hour
    if minute is None:
        minute = time_bj.minute
    time_rate = min((hour * 60 + minute) / (22 * 60), 1)
    min_step = get_int_value_default(config, 'MIN_STEP', 18000)
    max_step = get_int_value_default(config, 'MAX_STEP', 25000)
    return int(time_rate * min_step), int(time_rate * max_step)

# ==================== 线性步数增长算法 ====================

def load_step_state():
    if os.path.exists(STEP_STATE_FILE):
        try:
            with open(STEP_STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取步数状态失败: {e}")
            return None
    return None

def save_step_state(state):
    try:
        with open(STEP_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        print(f"已保存步数状态: {state['current_step']} 步 (第{state['run_count']}次)")
    except Exception as e:
        print(f"保存步数状态失败: {e}")

def get_linear_step():
    """
    线性增长算法：保证步数严格单调递增
    新增: 最低步数保护(MIN_CURRENT_STEP)，防止状态文件过期导致步数倒退
    """
    current_time = get_beijing_time()
    current_minute = current_time.hour * 60 + current_time.minute
    target_max = get_int_value_default(config, 'MAX_STEP', 25000)
    target_min = get_int_value_default(config, 'MIN_STEP', 18000)
    min_inc = get_int_value_default(config, 'MIN_INCREMENT', 800)
    max_inc = get_int_value_default(config, 'MAX_INCREMENT', 3000)

    # 【新增】最低步数保护 - 防止步数倒退
    # 当实际步数已高于状态文件记录时，用此值作为最低基准（在CONFIG中设置 MIN_CURRENT_STEP）
    min_current_step = get_int_value_default(config, 'MIN_CURRENT_STEP', 0)

    state = load_step_state()

    # 新的一天检测重置
    if state is not None:
        last_time_str = state.get('last_time')
        if last_time_str:
            last_date = datetime.strptime(last_time_str[:10], "%Y-%m-%d").date()
            if last_date < current_time.date():
                print(f"新的一天 ({last_date} -> {current_time.date()})，重置步数")
                state = None

    # 首次运行或新的一天
    if state is None:
        time_rate = min(current_minute / (22 * 60), 1)
        initial_step = int(target_min * time_rate) + random.randint(0, max(int((target_max - target_min) * time_rate * 0.3), 500))

        # 【新增】应用最低步数保护 - 确保不会从低于实际步数的值开始
        if min_current_step > 0:
            initial_step = max(initial_step, min_current_step)
            print(f"[步数保护] 启用最低步数保护: >= {min_current_step}")

        initial_step = max(initial_step, random.randint(500, 2000))

        new_state = {
            'current_step': initial_step,
            'last_time': format_now(),
            'last_minute': current_minute,
            'target_step': target_max,
            'day_start_time': format_now(),
            'run_count': 1
        }
        save_step_state(new_state)
        return initial_step

    # 非首次：线性增量
    last_step = state['current_step']
    last_minute = state['last_minute']
    run_count = state['run_count']

    # 【新增】如果配置了最低步数且比记录值高，提升基准防止倒退
    if min_current_step > 0 and min_current_step > last_step:
        print(f"[步数保护] 检测到 MIN_CURRENT_STEP({min_current_step}) > 记录步数({last_step})，调整基准")
        last_step = min_current_step

    time_diff = max(current_minute - last_minute, 1)
    total_window = 22 * 60
    remaining_steps = target_max - last_step

    # 基础增量
    base_increment = int(remaining_steps * (time_diff / total_window) * 0.8)
    increment = max(min_inc, min(base_increment, max_inc))

    # 自然波动 ±20%
    fluctuation = random.uniform(0.8, 1.2)
    increment = int(increment * fluctuation)

    new_step = last_step + increment
    new_step = max(last_step + min_inc // 2, min(new_step, target_max))

    # 更新状态
    new_state = {
        'current_step': new_step,
        'last_time': format_now(),
        'last_minute': current_minute,
        'target_step': target_max,
        'day_start_time': state.get('day_start_time', format_now()),
        'run_count': run_count + 1
    }
    save_step_state(new_state)

    print(f"[线性增长] {last_step} -> {new_step} (+{new_step - last_step}, 第{run_count+1}次)")
    return new_step

# ==================== 工具函数 ====================

def fake_ip():
    return f"{223}.{random.randint(64, 117)}.{random.randint(0, 255)}.{random.randint(0, 255)}"

def desensitize_user_name(user):
    if len(user) <= 8:
        ln = max(math.floor(len(user) / 3), 1)
        return f'{user[:ln]}***{user[-ln:]}'
    return f'{user[:3]}****{user[-4:]}'

def get_beijing_time():
    return datetime.now().astimezone(pytz.timezone('Asia/Shanghai'))

def format_now():
    return get_beijing_time().strftime("%Y-%m-%d %H:%M:%S")

def get_time():
    return "%.0f" % (get_beijing_time().timestamp() * 1000)

def get_access_token(location):
    m = re.search("(?<=access=).*?(?=&)", location)
    return m.group(0) if m else None

def get_error_code(location):
    m = re.search("(?<=error=).*?(?=&)", location)
    return m.group(0) if m else None

class MiMotionRunner:
    def __init__(self, _user, _passwd):
        self.user_id = None
        self.device_id = str(uuid.uuid4())
        self.invalid = False
        self.log_str = ""
        user = str(_user)
        password = str(_passwd)
        if user == '' or password == '':
            self.error = "用户名或密码填写有误！"
            self.invalid = True
        self.password = password
        if (user.startswith("+86")) or "@" in user:
            user = user
        else:
            user = "+86" + user
        self.is_phone = user.startswith("+86")
        self.user = user

    def login(self):
        user_token_info = user_tokens.get(self.user)
        if user_token_info is not None:
            access_token = user_token_info.get("access_token")
            login_token = user_token_info.get("login_token")
            app_token = user_token_info.get("app_token")
            self.device_id = user_token_info.get("device_id") or str(uuid.uuid4())
            self.user_id = user_token_info.get("user_id")
            if self.device_id:
                user_token_info["device_id"] = self.device_id
            ok, msg = zeppHelper.check_app_token(app_token)
            if ok:
                self.log_str += "使用加密保存的app_token\n"
                return app_token
            self.log_str += f"app_token失效，重新获取\n"
            app_token, msg = zeppHelper.grant_app_token(login_token)
            if app_token is None:
                self.log_str += f"login_token失效，重新获取\n"
                login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id, self.is_phone)
                if login_token is None:
                    self.log_str += f"access_token已失效: {msg}\n"
                else:
                    for k, v in [("login_token", login_token), ("app_token", app_token), ("user_id", user_id)]:
                        user_token_info[k] = v
                    user_token_info["login_token_time"] = get_time()
                    user_token_info["app_token_time"] = get_time()
                    self.user_id = user_id
                    return app_token
            else:
                self.log_str += "重新获取app_token成功\n"
                user_token_info["app_token"] = app_token
                user_token_info["app_token_time"] = get_time()
                return app_token
        access_token, msg = zeppHelper.login_access_token(self.user, self.password)
        if access_token is None:
            self.log_str += f"登录失败: {msg}"
            return None
        login_token, app_token, user_id, msg = zeppHelper.grant_login_tokens(access_token, self.device_id, self.is_phone)
        if login_token is None:
            self.log_str += f"access_token无效: {msg}"
            return None
        user_token_info = {
            "access_token": access_token,
            "login_token": login_token,
            "app_token": app_token,
            "user_id": user_id,
            "access_token_time": get_time(),
            "login_token_time": get_time(),
            "app_token_time": get_time(),
            "device_id": self.device_id
        }
        user_tokens[self.user] = user_token_info
        self.user_id = user_id
        return app_token

    def login_and_post_step_linear(self):
        if self.invalid:
            return "账号或密码配置有误", False
        app_token = self.login()
        if app_token is None:
            return "登录失败！", False
        step = str(get_linear_step())
        self.log_str += f"使用线性增长模式设置步数: {step}\n"
        ok, msg = zeppHelper.post_fake_brand_data(step, app_token, self.user_id)
        return f"修改步数({step})[线性增长]{msg}", ok

    def login_and_post_step(self, min_step, max_step):
        if self.invalid:
            return "账号或密码配置有误", False
        app_token = self.login()
        if app_token is None:
            return "登录失败！", False
        step = str(random.randint(min_step, max_step))
        self.log_str += f"随机步数({min_step}~{max_step}): {step}\n"
        ok, msg = zeppHelper.post_fake_brand_data(step, app_token, self.user_id)
        return f"修改步数({step})[{msg}]", ok

def run_single_account(total, idx, user_mi, passwd_mi, use_linear=True):
    idx_info = f"[{idx + 1}/{total}]"
    log_str = f"[{format_now()}]\n{idx_info}账号:{desensitize_user_name(user_mi)}\n"
    try:
        runner = MiMotionRunner(user_mi, passwd_mi)
        if use_linear:
            exec_msg, success = runner.login_and_post_step_linear()
        else:
            exec_msg, success = runner.login_and_post_step(min_step, max_step)
        log_str += runner.log_str
        log_str += f"{exec_msg}\n"
        exec_result = {"user": user_mi, "success": success, "msg": exec_msg}
    except Exception as e:
        log_str += f"执行异常: {traceback.format_exc()}\n"
        exec_result = {"user": user_mi, "success": False, "msg": f"异常: {e}"}
    print(log_str)
    return exec_result

def execute():
    global users, passwords, config, use_concurrent, sleep_seconds, min_step, max_step
    user_list = users.split('#')
    passwd_list = passwords.split('#')
    exec_results = []
    use_linear_mode = config.get('USE_LINEAR_MODE', 'True').lower() == 'true'

    if use_linear_mode:
        print("=" * 50)
        print("线性增长模式")
        print(f" 目标范围: {get_int_value_default(config, 'MIN_STEP', 18000)} ~ {get_int_value_default(config, 'MAX_STEP', 25000)}")
        print(f" 增量范围: {get_int_value_default(config, 'MIN_INCREMENT', 800)} ~ {get_int_value_default(config, 'MAX_INCREMENT', 3000)}")
        print("=" * 50)

    if len(user_list) == len(passwd_list):
        idx, total = 0, len(user_list)
        if use_concurrent:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                exec_results = list(executor.map(
                    lambda x: run_single_account(total, x[0], *x[1], use_linear_mode),
                    enumerate(zip(user_list, passwd_list))))
        else:
            for user_mi, passwd_mi in zip(user_list, passwd_list):
                exec_results.append(run_single_account(total, idx, user_mi, passwd_mi, use_linear_mode))
                idx += 1
                if idx < total:
                    time.sleep(sleep_seconds)
        if encrypt_support:
            persist_user_tokens()
        success_count = sum(1 for r in exec_results if r['success'])
        push_results = list(exec_results)
        summary = f"\n执行账号总数{total}, 成功:{success_count}, 失败:{total - success_count}"
        if use_linear_mode:
            summary += " [线性增长]"
        print(summary)
        push_util.push_results(push_results, summary, push_config)
    else:
        print(f"账号数[{len(user_list)}]和密码数[{len(passwd_list)}]不匹配")
        exit(1)

def prepare_user_tokens():
    path = r"encrypted_tokens.data"
    if os.path.exists(path):
        with open(path, 'rb') as f:
            data = f.read()
        try:
            return json.loads(decrypt_data(data, aes_key, None).decode('utf-8'))
        except:
            print("密钥错误或数据损坏，放弃token")
            return {}
    return {}

def persist_user_tokens():
    path = r"encrypted_tokens.data"
    cipher_data = encrypt_data(json.dumps(user_tokens, ensure_ascii=False).encode("utf-8"), aes_key, None)
    with open(path, 'wb') as f:
        f.write(cipher_data)
        f.flush()

if __name__ == "__main__":
    time_bj = get_beijing_time()
    encrypt_support = False
    user_tokens = {}

    if os.environ.__contains__("AES_KEY"):
        aes_key = os.environ.get("AES_KEY", "").encode('utf-8')
        if len(aes_key) == 16:
            encrypt_support = True
            user_tokens = prepare_user_tokens()
        else:
            print("AES_KEY无效")

    if not os.environ.__contains__("CONFIG"):
        print("未配置CONFIG变量")
        exit(1)

    try:
        config = dict(json.loads(os.environ.get("CONFIG")))
    except:
        print("CONFIG格式错误")
        traceback.print_exc()
        exit(1)

    push_config = push_util.PushConfig(
        push_plus_token=config.get('PUSH_PLUS_TOKEN'),
        push_plus_hour=config.get('PUSH_PLUS_HOUR'),
        push_plus_max=get_int_value_default(config, 'PUSH_PLUS_MAX', 30),
        push_wechat_webhook_key=config.get('PUSH_WECHAT_WEBHOOK_KEY'),
        telegram_bot_token=config.get('TELEGRAM_BOT_TOKEN'),
        telegram_chat_id=config.get('TELEGRAM_CHAT_ID')
    )

    sleep_seconds = float(config.get('SLEEP_GAP') or 5)
    users = config.get('USER')
    passwords = config.get('PWD')

    if not users or not passwords:
        print("未正确配置账号密码")
        exit(1)

    min_step, max_step = get_min_max_by_time()
    use_concurrent = config.get('USE_CONCURRENT') == 'True'
    if not use_concurrent:
        print(f"多账号间隔: {sleep_seconds}s")

    execute()
