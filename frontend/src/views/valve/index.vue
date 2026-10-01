<template>
  <section class="page" data-module="valve">
    <header class="page-head">
      <div>
        <h2>阀门井室管理</h2>
        <p class="page-desc">阀门状态顺着「安排启闭 → 操作正常/启闭卡涩 → 卡涩复核 → 停用」推进，不允许跳级；停用必须写清原因并留痕。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记阀门</button>
        <button class="btn" type="button" @click="exportRows">导出阀门井室清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>阀门编号</span>
        <input v-model="filters.keyword" placeholder="按阀门编号检索" />
      </label>
      <label class="filter-item">
        <span>阀门状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actionsOf(row)"
              :key="action"
              class="link"
              type="button"
              @click="startAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="!actionsOf(row).length" class="muted-text">已停用，流程结束</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无阀门井室数据，可先登记阀门</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条阀门井室记录</span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialog" class="modal-mask" @click.self="closeDialog">
      <div class="modal-card">
        <template v-if="dialog.kind === 'retire'">
          <h3>停用阀门 {{ dialog.row['阀门编号'] }}</h3>
          <p class="modal-desc">停用后阀门退出待启闭清单，流程不可恢复；必须写清停用原因，并保留状态变更记录。</p>
          <label class="modal-field">
            <span>停用原因（必填）</span>
            <textarea v-model="retireReason" rows="3" placeholder="例如：阀体锈蚀严重，已列入更换计划"></textarea>
          </label>
          <div class="modal-actions">
            <button class="btn primary" type="button" @click="submitRetire">确认停用</button>
            <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          </div>
        </template>

        <template v-else-if="dialog.kind === 'review'">
          <h3>卡涩复核 {{ dialog.row['阀门编号'] }}</h3>
          <p class="modal-desc">复核通过才允许回到「操作正常」；不通过则保持「启闭卡涩」，复核结论会写入变更记录。</p>
          <label class="modal-field">
            <span>复核结论</span>
            <select v-model="reviewResult">
              <option v-for="item in reviewResults" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="modal-field">
            <span>复核说明</span>
            <textarea v-model="reviewNote" rows="3" placeholder="例如：加注润滑脂后全程启闭灵活"></textarea>
          </label>
          <div class="modal-actions">
            <button class="btn primary" type="button" @click="submitReview">提交复核</button>
            <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          </div>
        </template>

        <template v-else-if="dialog.kind === 'create'">
          <h3>登记阀门</h3>
          <p class="modal-desc">登记后进入「待启闭」清单，带 * 为必填项。</p>
          <label v-for="field in createFields" :key="field.name" class="modal-field">
            <span>{{ field.name }}{{ field.required ? ' *' : '' }}</span>
            <input v-model="createForm[field.name]" :placeholder="`请输入${field.name}`" />
          </label>
          <div class="modal-actions">
            <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
            <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          </div>
        </template>

        <template v-else-if="dialog.kind === 'detail'">
          <h3>阀门详情 {{ dialog.row['阀门编号'] }}</h3>
          <table class="data-table detail-table">
            <tbody>
              <tr v-for="column in columns" :key="column">
                <th>{{ column }}</th>
                <td>{{ dialog.row[column] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
          <h4 class="history-title">状态变更记录</h4>
          <table class="data-table">
            <thead>
              <tr><th>时间</th><th>动作</th><th>变更前</th><th>变更后</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in dialog.history" :key="index">
                <td>{{ item['时间'] }}</td>
                <td>{{ item['动作'] }}</td>
                <td>{{ item['变更前'] }}</td>
                <td>{{ item['变更后'] }}</td>
                <td>{{ item['说明'] || '—' }}</td>
              </tr>
              <tr v-if="!dialog.history.length">
                <td colspan="5" class="empty-state">暂无变更记录</td>
              </tr>
            </tbody>
          </table>
          <div class="modal-actions">
            <button class="btn ghost" type="button" @click="closeDialog">关闭</button>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null> & { id: number }
type HistoryItem = { 时间: string; 动作: string; 变更前: string; 变更后: string; 说明: string }
type Dialog =
  | { kind: 'retire' | 'review'; row: Row }
  | { kind: 'create' }
  | { kind: 'detail'; row: Row; history: HistoryItem[] }

const ENDPOINT = '/api/valve'
const columns = ["阀门编号", "阀门类别", "所在管段", "公称直径", "操作方向", "上次启闭日", "责任人员", "阀门状态"]
const statuses = ["待启闭", "操作正常", "启闭卡涩", "已停用"]
const reviewResults = ["通过", "不通过"]
// 每个状态允许执行的动作：与后端状态机保持一致，已停用不再出现任何动作
const actionsByStatus: Record<string, string[]> = {
  '待启闭': ['确认正常', '确认卡涩', '停用阀门'],
  '操作正常': ['安排启闭', '停用阀门'],
  '启闭卡涩': ['卡涩复核', '停用阀门'],
  '已停用': [],
}
const createFields = [
  { name: '阀门编号', required: true },
  { name: '阀门类别', required: true },
  { name: '所在管段', required: true },
  { name: '公称直径', required: false },
  { name: '操作方向', required: false },
  { name: '上次启闭日', required: false },
  { name: '责任人员', required: false },
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '在册阀门', value: 0 },
  { label: '待启闭阀门', value: 0 },
  { label: '启闭卡涩', value: 0 },
  { label: '已停用', value: 0 },
])
const errorMessage = ref('')
const notice = ref('')
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const dialog = ref<Dialog | null>(null)
const retireReason = ref('')
const reviewResult = ref('通过')
const reviewNote = ref('')
const createForm = ref<Record<string, string>>({})

function actionsOf(row: Row): string[] {
  return actionsByStatus[String(row['阀门状态'] ?? row.status ?? '')] ?? []
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  dialog.value = { kind: 'create' }
}

function closeDialog() {
  dialog.value = null
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const detail = await fetchJson<Row & { history?: HistoryItem[] }>(`${ENDPOINT}/${row.id}`)
    dialog.value = { kind: 'detail', row: detail, history: detail.history ?? [] }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门详情读取失败'
  }
}

function startAction(action: string, row: Row) {
  notice.value = ''
  errorMessage.value = ''
  if (action === '停用阀门') {
    retireReason.value = ''
    dialog.value = { kind: 'retire', row }
    return
  }
  if (action === '卡涩复核') {
    reviewResult.value = '通过'
    reviewNote.value = ''
    dialog.value = { kind: 'review', row }
    return
  }
  void submitAction(action, row)
}

async function submitRetire() {
  const current = dialog.value
  if (!current || current.kind !== 'retire') return
  const row = current.row
  closeDialog()
  await submitAction('停用阀门', row, { reason: retireReason.value })
}

async function submitReview() {
  const current = dialog.value
  if (!current || current.kind !== 'review') return
  const row = current.row
  closeDialog()
  await submitAction('卡涩复核', row, { result: reviewResult.value, note: reviewNote.value })
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload.message ?? '阀门登记未生效'
      return
    }
    closeDialog()
    notice.value = payload.message ?? '阀门已登记'
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门登记失败'
  }
}

async function submitAction(action: string, row: Row, extra: Record<string, string> = {}) {
  errorMessage.value = ''
  notice.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, ...extra } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 操作未成功：后端保留原状态，这里只说明原因，不改动本地数据
      errorMessage.value = payload.message ?? '阀门井室动作未生效'
      return
    }
    notice.value = payload.message ?? `阀门已${action}`
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门井室操作失败'
  }
}

async function reload() {
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  try {
    const payload = await fetchJson<{ items: Row[]; total: number }>(`${ENDPOINT}?${query}`)
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '阀门井室列表读取失败'
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<{ total: number; by_status: Record<string, number> }>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '在册阀门', value: payload.total },
      { label: '待启闭阀门', value: payload.by_status['待启闭'] ?? 0 },
      { label: '启闭卡涩', value: payload.by_status['启闭卡涩'] ?? 0 },
      { label: '已停用', value: payload.by_status['已停用'] ?? 0 },
    ]
  } catch {
    // 汇总读取失败时保留上一次数据，不打断列表操作
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
