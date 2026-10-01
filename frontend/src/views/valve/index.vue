<template>
  <section class="page" data-module="valve">
    <header class="page-head">
      <div>
        <h2>阀门井室管理</h2>
        <p class="page-desc">阀门状态顺着「待启闭 → 操作正常/启闭卡涩 → 卡涩复核 → 已停用」推进，不允许跳级；停用必须写明原因。</p>
      </div>
      <div class="page-actions">
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
        <input v-model="keyword" placeholder="按阀门编号检索" />
      </label>
      <label class="filter-item">
        <span>阀门状态</span>
        <select v-model="statusFilter">
          <option value="">待启闭清单（不含已停用）</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          <option value="__all__">全部（含已停用）</option>
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
          <th>明细</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '阀门状态'" class="status-tag" :data-status="row.status">{{ row.status }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-if="row.status === '待启闭'">
              <button class="link" type="button" @click="reportResult(row, '操作正常')">启闭正常</button>
              <button class="link danger" type="button" @click="reportResult(row, '启闭卡涩')">启闭卡涩</button>
              <button class="link danger" type="button" @click="askDisable(row)">停用阀门</button>
            </template>
            <template v-else-if="row.status === '启闭卡涩'">
              <button class="link" type="button" @click="askRecheck(row, '复核通过')">复核通过</button>
              <button class="link danger" type="button" @click="askRecheck(row, '复核未通过')">复核未通过</button>
              <button class="link danger" type="button" @click="askDisable(row)">停用阀门</button>
            </template>
            <template v-else-if="row.status === '操作正常'">
              <button class="link danger" type="button" @click="askDisable(row)">停用阀门</button>
            </template>
            <template v-else>
              <span class="muted-text">已停用，不可操作</span>
            </template>
          </td>
          <td>
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">当前筛选条件下没有阀门记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条阀门井室记录<span v-if="statusFilter !== '已停用' && statusFilter !== '__all__'">（已停用阀门不列入待启闭清单）</span></span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <div v-if="detail" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer">
        <header class="drawer-head">
          <h3>阀门详情 · {{ detail['阀门编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <p><span class="status-tag" :data-status="detail.status">{{ detail.status }}</span></p>
        <dl class="detail-grid">
          <template v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ column === '阀门状态' ? detail.status : (detail[column] ?? '—') }}</dd>
          </template>
          <template v-if="detail.status === '已停用'">
            <dt>停用原因</dt>
            <dd>{{ detail['停用原因'] || '—' }}</dd>
          </template>
        </dl>
        <h4 class="history-title">状态变更记录</h4>
        <table class="data-table history-table">
          <thead>
            <tr><th>时间</th><th>动作</th><th>变更前</th><th>变更后</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in detail.history || []" :key="index">
              <td>{{ item.time }}</td>
              <td>{{ item.action }}</td>
              <td>{{ item.from }}</td>
              <td>{{ item.to }}</td>
              <td>{{ item.note || '—' }}</td>
            </tr>
            <tr v-if="!(detail.history && detail.history.length)">
              <td colspan="5" class="empty-state">暂无变更记录</td>
            </tr>
          </tbody>
        </table>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type HistoryItem = { time: string; action: string; from: string; to: string; note: string }
type Row = Record<string, string | number | boolean | null> & {
  id: number
  status: string
  history?: HistoryItem[]
  停用原因?: string
}
type Stats = { total: number; pending: number; normal: number; stuck: number; disabled: number; worklist: number }

const ENDPOINT = '/api/valve'
const columns = ['阀门编号', '阀门类别', '所在管段', '公称直径', '操作方向', '上次启闭日', '责任人员', '阀门状态']
const statuses = ['待启闭', '操作正常', '启闭卡涩', '已停用']

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([
  { label: '在册阀门', value: 0 },
  { label: '待启闭清单', value: 0 },
  { label: '操作正常', value: 0 },
  { label: '启闭卡涩', value: 0 },
  { label: '已停用', value: 0 },
])
const message = ref('')
const messageOk = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const detail = ref<Row | null>(null)

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function postAction(row: Row, values: Record<string, string>) {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 操作没成功：后端不改状态，前端也不刷新覆盖，原样保留并说明原因。
      messageOk.value = false
      message.value = payload.message || '阀门井室动作未生效，状态保持不变'
      return
    }
    messageOk.value = true
    message.value = payload.message
    await Promise.all([reload(), reloadStats()])
    if (detail.value && detail.value.id === row.id) {
      await openDetail(payload.entry as Row)
    }
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '阀门井室操作失败，状态保持不变'
  }
}

function reportResult(row: Row, result: string) {
  void postAction(row, { action: '安排启闭', result })
}

function askRecheck(row: Row, result: string) {
  if (result === '复核未通过') {
    const note = window.prompt('卡涩复核未通过，请填写现场情况（留空也可）：', '')
    if (note === null) return
    void postAction(row, { action: '卡涩复核', result, note })
    return
  }
  void postAction(row, { action: '卡涩复核', result })
}

function askDisable(row: Row) {
  const reason = window.prompt(`停用阀门「${row['阀门编号']}」前必须写明停用原因：`, '')
  if (reason === null) return
  if (!reason.trim()) {
    messageOk.value = false
    message.value = '停用阀门前必须写清停用原因，状态保持不变'
    return
  }
  void postAction(row, { action: '停用阀门', reason: reason.trim() })
}

async function openDetail(row: Row) {
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('阀门详情读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '阀门详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('状态统计读取失败')
    }
    const data = (await response.json()) as Stats
    stats.value = [
      { label: '在册阀门', value: data.total },
      { label: '待启闭清单', value: data.worklist },
      { label: '操作正常', value: data.normal },
      { label: '启闭卡涩', value: data.stuck },
      { label: '已停用', value: data.disabled },
    ]
  } catch {
    // 统计读不出来时保留上一次的卡片数值，不动列表口径
  }
}

async function reload() {
  message.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value === '__all__') {
    query.set('include_disabled', 'true')
  } else if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('阀门列表读取失败')
    }
    const payload = await response.json()
    rows.value = (payload.items ?? []) as Row[]
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '阀门井室列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
