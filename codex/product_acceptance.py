"""Real-browser acceptance; requires the isolated test_server.py, never a user database."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'codex/evidence'
API = 'http://127.0.0.1:8000'
WEEK = '2026-10-05'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token', required=True)
    args = parser.parse_args()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    results = []
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'cases': results, 'runtime_errors': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(locale='zh-CN', timezone_id='America/Los_Angeles', viewport={'width': 1440, 'height': 1000})
        def isolated_api_only(route):
            if route.request.url.startswith(API + '/api/'):
                route.continue_()
            else:
                route.abort('blockedbyclient')
        context.route('**/api/**', isolated_api_only)
        page = context.new_page()
        page.on('pageerror', lambda error: report['runtime_errors'].append(str(error)))

        def passed(name, evidence=None):
            results.append({'name': name, 'status': 'passed', 'evidence': evidence})
            print(f'PASS: {name}', flush=True)

        def get(path):
            response = context.request.get(API + path)
            assert response.ok, f'{path}: {response.status} {response.text()}'
            return response.json()

        def shot(name):
            page.screenshot(path=str(EVIDENCE / name), full_page=True)

        def tab(name):
            page.get_by_role('navigation').get_by_role('button', name=name, exact=True).click()
            page.wait_for_load_state('networkidle')

        def create_task(title, duration=60, deadline='2026-10-05T18:00', priority='normal'):
            tab('任务')
            form = page.locator('form').filter(has=page.get_by_role('button', name='添加任务', exact=True))
            form.get_by_label('标题', exact=True).fill(title)
            form.get_by_label('预计时长（分钟）', exact=True).fill(str(duration))
            form.get_by_label('截止时间（北京时间）', exact=True).fill(deadline)
            form.get_by_label('优先级').select_option(priority)
            form.get_by_role('button', name='添加任务', exact=True).click()
            expect(page.locator('article').filter(has=page.get_by_role('heading', name=title, exact=True))).to_be_visible()
            return next(task for task in get('/api/tasks') if task['title'] == title)

        def add_rule(kind, title, start, end):
            name = '课程' if kind == 'course' else '保留时间'
            section = page.get_by_role('region', name=name, exact=True)
            section.get_by_role('button', name='添加' + name, exact=True).click()
            section.get_by_label('标题', exact=True).fill(title)
            section.get_by_label('星期').select_option('1')
            section.get_by_label('开始时间', exact=True).fill(start)
            section.get_by_label('结束时间', exact=True).fill(end)
            section.get_by_role('button', name='添加' + name, exact=True).click()
            expect(section.get_by_role('heading', name=title, exact=True)).to_be_visible()

        def weekly():
            tab('周计划')
            page.get_by_label('选择周日期', exact=True).fill(WEEK)
            expect(page.get_by_role('button', name='生成候选计划', exact=True)).to_be_enabled()
            page.wait_for_load_state('networkidle')

        def choose(*titles):
            for checkbox in page.locator('.task-selection input').all():
                checkbox.uncheck()
            for title in titles:
                page.get_by_role('checkbox', name=re.compile(re.escape(title))).check()

        def generate():
            with page.expect_response(lambda r: r.url.endswith('/api/plans/candidates') and r.request.method == 'POST') as response:
                page.get_by_role('button', name='生成候选计划', exact=True).click()
            assert response.value.ok, response.value.text()
            plan = response.value.json()['candidate']
            expect(page.get_by_role('button', name='确认候选计划', exact=True)).to_be_enabled()
            return plan

        def confirm():
            with page.expect_response(lambda r: r.url.endswith('/confirm') and r.request.method == 'POST') as response:
                page.get_by_role('button', name='确认候选计划', exact=True).click()
            assert response.value.ok, response.value.text()
            plan = response.value.json()
            expect(page.get_by_text(f'计划 #{plan["id"]} 已确认为正式计划。', exact=True)).to_be_visible()
            page.wait_for_load_state('networkidle')
            assert get('/api/plans/confirmed?week_start=' + WEEK)['id'] == plan['id']
            return plan

        try:
            # Guard against accidentally writing to a previously used or ordinary database.
            identity = get('/__acceptance__/identity')
            assert identity['mode'] == 'isolated-product-acceptance' and identity['token'] == args.token
            assert identity['database'].startswith('acceptance-')
            report['isolated_database'] = identity['database']
            assert get('/api/tasks') == [], 'Acceptance requires a NEW empty isolated database.'
            assert get('/api/time-rules') == []
            # The test server deliberately forces this no-provider response.
            unavailable = context.request.post(API + '/api/constraints/parse', data={'text': '每周三下午两点到四点实验课'})
            assert unavailable.status == 503 and unavailable.json()['detail']['code'] == 'AI_NOT_CONFIGURED'
            page.goto('http://localhost:5173')
            page.wait_for_load_state('networkidle')
            expect(page.locator('html')).to_have_attribute('lang', 'zh-CN')
            expect(page.get_by_text('还没有任务，请先添加。', exact=True)).to_be_visible()
            tab('课程与保留时间')
            expect(page.get_by_text('还没有课程，请先添加。', exact=True)).to_be_visible()
            weekly()
            expect(page.get_by_text('没有待完成任务，请先在“任务”页面添加。', exact=True)).to_be_visible()
            passed('三个页面中文空状态及语言标记')

            tab('任务')
            page.get_by_label('标题', exact=True).fill(' ')
            page.get_by_label('截止时间（北京时间）', exact=True).fill('2026-10-05T18:00')
            page.get_by_role('button', name='添加任务', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('标题：不能为空')
            assert get('/api/tasks') == []
            passed('空白标题由真实后端拒绝，显示中文纠正提示')

            report_task = create_task('完成课程报告')
            reading_task = create_task('阅读课程资料')
            card = page.locator('article').filter(has=page.get_by_role('heading', name='完成课程报告', exact=True))
            card.get_by_role('button', name='编辑', exact=True).click()
            card.get_by_label(re.compile('说明')).fill('先完成提纲，再补充验证结果。')
            card.get_by_role('button', name='保存任务', exact=True).click()
            expect(card.get_by_text('先完成提纲，再补充验证结果。', exact=True)).to_be_visible()
            stored = get('/api/tasks')
            assert stored[0]['deadline'] == report_task['deadline'] and stored[0]['priority'] == 'normal'
            shot('02-tasks-filled.png')
            passed('任务新增、编辑、时区及英文接口枚举保留')

            tab('课程与保留时间')
            add_rule('course', '软件工程课', '09:00', '10:00')
            add_rule('protected', '早餐与通勤', '08:00', '09:00')
            assert [r['weekday'] for r in get('/api/time-rules')] == [1, 1]
            expect(page.get_by_text('每周一', exact=True).first).to_be_visible()
            page.get_by_label('描述你的时间安排', exact=True).fill('每周三下午两点到四点实验课')
            page.get_by_role('button', name='用 AI 解析', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('AI 解析暂不可用')
            assert len(get('/api/time-rules')) == 2
            shot('03-rules-ai-unavailable.png')
            passed('课程及保留时间新增；真实 AI 未配置时手动流程可用')

            weekly()
            page.get_by_role('button', name='生成候选计划', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('请至少选择一个任务')
            choose('完成课程报告', '阅读课程资料')
            first = generate()
            task_items = [item for item in first['items'] if item['kind'] == 'task']
            assert [item['start_at'] for item in task_items] == ['2026-10-05T02:00:00Z', '2026-10-05T03:00:00Z']
            assert len([item for item in first['items'] if item['kind'] == 'course']) == 1
            assert context.request.get(API + '/api/plans/confirmed?week_start=' + WEEK).status == 404
            expect(page.get_by_text('这是本周的首次候选计划。', exact=True)).to_be_visible()
            page.get_by_role('checkbox', name=re.compile('阅读课程资料')).uncheck()
            expect(page.get_by_role('button', name='确认候选计划', exact=True)).to_be_disabled()
            page.get_by_role('checkbox', name=re.compile('阅读课程资料')).check()
            expect(page.get_by_role('button', name='确认候选计划', exact=True)).to_be_enabled()
            shot('04-first-candidate.png')
            passed('排程避开课程和保留时间；候选独立；任务选择变化阻止确认')
            official = confirm()
            passed('首次确认并从数据库读回正式计划')

            create_task('临时提交材料', 30, '2026-10-05T10:30', 'high')
            weekly()
            choose('完成课程报告', '阅读课程资料', '临时提交材料')
            replacement = generate()
            assert replacement['based_on_plan_id'] == official['id']
            assert get('/api/plans/confirmed?week_start=' + WEEK)['id'] == official['id']
            with page.expect_response(lambda r: r.url.endswith('/explanation')) as response:
                page.get_by_role('button', name='查看变化说明', exact=True).click()
            explanation = response.value.json()
            assert explanation['explanation_status'] == 'unavailable'
            assert explanation['diff']['summary']['added_count'] == 1 and explanation['diff']['summary']['moved_count'] == 2
            assert response.value.request.post_data_json == {'language': 'zh-CN'}
            expect(page.get_by_text('AI 说明暂不可用，仍可查看计划变化并确认方案。', exact=True)).to_be_visible()
            shot('05-replanning-diff.png')
            passed('临时任务重排、旧正式计划保留、中文变化列表及 AI 说明降级')
            official = confirm()
            assert get('/api/plans/' + str(first['id']))['status'] == 'superseded'
            passed('确认替换方案，旧计划标记为已替换')

            generate()
            tab('任务')
            card = page.locator('article').filter(has=page.get_by_role('heading', name='完成课程报告', exact=True))
            card.get_by_role('button', name='编辑', exact=True).click()
            card.get_by_label(re.compile('说明')).fill('增加了课程验收要求。')
            card.get_by_role('button', name='保存任务', exact=True).click()
            expect(card.get_by_text('增加了课程验收要求。', exact=True)).to_be_visible()
            weekly()
            with page.expect_response(lambda r: r.url.endswith('/confirm')) as response:
                page.get_by_role('button', name='确认候选计划', exact=True).click()
            assert response.value.status == 409 and response.value.json()['detail']['code'] == 'STALE_CANDIDATE'
            expect(page.get_by_role('alert')).to_contain_text('候选计划已过期')
            expect(page.get_by_role('button', name='确认候选计划', exact=True)).to_be_disabled()
            assert get('/api/plans/confirmed?week_start=' + WEEK)['id'] == official['id']
            shot('06-stale-candidate.png')
            generate()
            official = confirm()
            passed('修改任务后拒绝旧候选；重新生成后恢复确认')

            create_task('超出单日容量的任务', 900)
            weekly()
            choose('超出单日容量的任务')
            with page.expect_response(lambda r: r.url.endswith('/candidates')) as response:
                page.get_by_role('button', name='生成候选计划', exact=True).click()
            assert response.value.status == 409 and response.value.json()['detail']['code'] == 'UNSCHEDULABLE'
            expect(page.get_by_role('alert')).to_contain_text('当前排程规则未找到完整方案')
            assert get('/api/plans/confirmed?week_start=' + WEEK)['id'] == official['id']
            shot('07-unschedulable.png')
            passed('无法完整排程时显示中文原因，正式计划不受影响')

            tab('任务')
            card = page.locator('article').filter(has=page.get_by_role('heading', name='超出单日容量的任务', exact=True))
            card.get_by_role('button', name='取消任务', exact=True).click()
            expect(card.get_by_text('已取消', exact=True)).to_be_visible()
            done = create_task('已完成的小练习', 30)
            card = page.locator('article').filter(has=page.get_by_role('heading', name=done['title'], exact=True))
            card.get_by_role('button', name='标记完成', exact=True).click()
            expect(card.get_by_text('已完成', exact=True)).to_be_visible()
            weekly()
            expect(page.get_by_role('checkbox', name=re.compile('超出单日容量'))).to_have_count(0)
            expect(page.get_by_role('checkbox', name=re.compile('已完成的小练习'))).to_have_count(0)
            page.reload()
            page.wait_for_load_state('networkidle')
            weekly()
            expect(page.get_by_role('region', name='当前正式计划', exact=True)).to_contain_text(f'计划 #{official["id"]}')
            passed('完成和取消状态排除；刷新后正式计划持久化')

            page.route('**/api/tasks', lambda route: route.abort('connectionrefused'))
            page.get_by_role('button', name='重新加载任务和正式计划', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('无法连接后端')
            page.unroute('**/api/tasks')
            page.get_by_role('button', name='重试', exact=True).click()
            expect(page.get_by_role('alert')).to_have_count(0)
            expect(page.get_by_role('checkbox', name=re.compile('完成课程报告'))).to_be_visible()
            passed('浏览器模拟断网后中文提示与手动重试恢复')

            # Only optional paid-provider responses are stubbed below; Apply uses real CRUD.
            tab('课程与保留时间')
            count_before = len(get('/api/time-rules'))
            proposal = {'kind': 'protected', 'title': '自主学习时间', 'recurrence': 'weekly', 'weekday': 3, 'date': None, 'start_time': '14:00', 'end_time': '16:00'}
            def parsed(route):
                route.fulfill(status=200, json={'status': 'parsed', 'proposal': proposal})
            page.route('**/api/constraints/parse', parsed)
            page.get_by_label('描述你的时间安排', exact=True).fill('每周三下午两点到四点留给自习')
            page.get_by_role('button', name='用 AI 解析', exact=True).click()
            expect(page.get_by_role('heading', name='AI 提案', exact=True)).to_be_visible()
            assert len(get('/api/time-rules')) == count_before
            page.get_by_role('button', name='放弃提案', exact=True).click()
            assert len(get('/api/time-rules')) == count_before
            page.get_by_role('button', name='用 AI 解析', exact=True).click()
            proposal_form = page.locator('.ai-result form')
            proposal_form.get_by_label('标题', exact=True).fill('确认后的自习时间')
            proposal_form.get_by_role('button', name='应用时间规则', exact=True).click()
            expect(page.get_by_text('时间规则已添加，可在下方列表中查看。', exact=True)).to_be_visible()
            assert len(get('/api/time-rules')) == count_before + 1
            assert get('/api/time-rules')[-1]['title'] == '确认后的自习时间'
            page.unroute('**/api/constraints/parse')
            passed('AI 提案预览、放弃不写入；编辑并应用才保存（提供者响应模拟）')

            for status, heading in [('needs_clarification', '需要补充信息'), ('unsupported', '暂不支持此请求')]:
                def notice_response(route):
                    route.fulfill(status=200, json={'status': status, 'message': 'Specific times required.'})
                page.route('**/api/constraints/parse', notice_response)
                page.get_by_label('描述你的时间安排', exact=True).fill('不完整的时间描述')
                page.get_by_role('button', name='用 AI 解析', exact=True).click()
                expect(page.get_by_role('heading', name=heading, exact=True)).to_be_visible()
                page.unroute('**/api/constraints/parse')
                assert len(get('/api/time-rules')) == count_before + 1
            passed('AI 补充信息和不支持请求中文提示，不写入数据（响应模拟）')

            for width in [390, 320]:
                page.set_viewport_size({'width': width, 'height': 844})
                for name in ['任务', '课程与保留时间', '周计划']:
                    tab(name)
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'{name}: horizontal overflow at {width}'
                    if width == 390:
                        shot({'任务': '08-mobile-tasks.png', '课程与保留时间': '09-mobile-rules.png', '周计划': '10-mobile-plans.png'}[name])
            passed('390px 和 320px 窄屏三个页面无横向溢出')
            assert not report['runtime_errors'], report['runtime_errors']
            report['status'] = 'passed'
        except Exception as error:
            report['status'] = 'failed'
            report['error'] = repr(error)
            shot('failure.png')
            raise
        finally:
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            (EVIDENCE / 'product-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()

if __name__ == '__main__':
    main()
