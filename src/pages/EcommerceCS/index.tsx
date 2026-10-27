import React, { useState, useEffect, useRef } from 'react';
import {
  Button,
  Input,
  Tag,
  Descriptions,
  Message,
  Progress,
  Tooltip,
  Select,
} from '@arco-design/web-react';
import styles from './index.module.less';

const TextArea = Input.TextArea;

// 默认 API 请求地址 (本地 FastAPI 后端)
const API_BASE = 'http://localhost:8000/api/v1';

interface ProductDisplay {
  screen_size: number;
  resolution: string;
  refresh_rate: number;
  color_gamut: string;
  brightness_nits?: number;
}

interface ProductHardware {
  cpu: string;
  gpu: string;
  tgp_watt: number;
  ram_installed: string;
  ram_slots: number;
  ram_max_gb: number;
  storage_installed: string;
  m2_slots_total: number;
  thunderbolt_port: boolean;
  weight_kg: number;
}

interface ProductItem {
  spu_code: string;
  title: string;
  category: string;
  official_price: number;
  specs: {
    display: ProductDisplay;
    hardware: ProductHardware;
    sales_pitch: string[];
    gift_policy: string;
  };
}

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming?: boolean;
  toolCalls?: Array<{ tool_name: string; arguments: any; cost_ms?: number }>;
  meta?: {
    trace_id?: string;
    prompt_version?: string;
    cost_ms?: number;
    is_cached?: boolean;
    llm_mode?: string;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
  };
}

interface SessionItem {
  session_id: string;
  spu_code?: string;
  title_summary: string;
  message_count: number;
  last_active_at: string;
  first_started_at?: string;
}

export default function EcommerceCSPage() {
  const [products, setProducts] = useState<ProductItem[]>([]);
  // 左侧栏 Tab 状态: 'gallery' (在售展台) | 'history' (历史会话)
  const [leftTab, setLeftTab] = useState<'gallery' | 'history'>('gallery');
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  // 默认进入全店通用咨询窗口（null 表示不绑定单一机型）
  const [selectedSpu, setSelectedSpu] = useState<string | null>(null);
  const [currentProduct, setCurrentProduct] = useState<ProductItem | null>(null);
  const [sessionId, setSessionId] = useState<string>(() => {
    return (
      localStorage.getItem('evoretail_active_session_id') ||
      `sess_web_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`
    );
  });

  // 右侧工作台 Tab 状态: 'facts' (硬件事实) | 'sandbox' (进化工坊沙箱)
  const [rightTab, setRightTab] = useState<'facts' | 'sandbox'>('facts');
  const [rightCollapsed, setRightCollapsed] = useState<boolean>(false);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '您好！我是惠普官方旗舰店金牌售前顾问【智小惠】。\n本店全线笔记本均享官方正品保障与全国联保，支持自行开盖加装固态与内存且不破坏整机质保。请问您平时选购电脑的主要用途是硬核 3A 电竞、4K 视频创作还是出差商务办公呢？',
      meta: {
        prompt_version: 'v2.0.0',
        llm_mode: 'live',
      },
    },
  ]);

  const [inputVal, setInputVal] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [isRunningSandbox, setIsRunningSandbox] = useState<boolean>(false);
  const [isOptimizing, setIsOptimizing] = useState<boolean>(false);
  const [versionList, setVersionList] = useState<any[]>([]);
  const [sandboxReport, setSandboxReport] = useState<any>(null);
  const [diagnoseReport, setDiagnoseReport] = useState<any>(null);

  const messageEndRef = useRef<HTMLDivElement>(null);

  const fetchVersions = async () => {
    try {
      const res = await fetch(`${API_BASE}/evolution/versions`);
      const data = await res.json();
      if (data.code === 200 && data.data) {
        setVersionList(data.data);
      }
    } catch (e) {
      console.warn('获取版本列表失败:', e);
    }
  };

  // 获取所有历史会话摘要列表
  const fetchSessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/chat/sessions?limit=50`);
      const data = await res.json();
      if (data.code === 200 && data.data) {
        setSessions(data.data);
      }
    } catch (e) {
      console.warn('获取会话列表失败:', e);
    }
  };

  // 拉取指定 session_id 的完整历史记录
  const loadSessionHistory = async (targetSessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/chat/history?session_id=${targetSessionId}`);
      const data = await res.json();
      if (data.code === 200 && data.data) {
        if (data.data.messages && data.data.messages.length > 0) {
          setMessages(data.data.messages);
        } else {
          setMessages([
            {
              id: 'welcome',
              role: 'assistant',
              content:
                '您好！我是惠普官方旗舰店金牌售前顾问【智小惠】。\n本店全线笔记本均享官方正品保障与全国联保，支持自行开盖加装固态与内存且不破坏整机质保。请问您平时选购电脑的主要用途是硬核 3A 电竞、4K 视频创作还是出差商务办公呢？',
              meta: {
                prompt_version: 'v2.0.0',
                llm_mode: 'live',
              },
            },
          ]);
        }
      }
    } catch (e) {
      console.warn('拉取会话历史失败:', e);
    }
  };

  // 切换指定历史会话并回填
  const handleSwitchSession = async (targetSessionId: string, spuCode?: string) => {
    setSessionId(targetSessionId);
    localStorage.setItem('evoretail_active_session_id', targetSessionId);
    await loadSessionHistory(targetSessionId);
    if (spuCode) {
      const matched = products.find((p) => p.spu_code === spuCode);
      if (matched) {
        setSelectedSpu(matched.spu_code);
        setCurrentProduct(matched);
      } else {
        setSelectedSpu(null);
        setCurrentProduct(null);
      }
    } else {
      setSelectedSpu(null);
      setCurrentProduct(null);
    }
    Message.info('已加载历史咨询记录');
  };

  // 开启全新咨询会话
  const handleCreateNewSession = () => {
    const newId = `sess_web_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
    setSessionId(newId);
    localStorage.setItem('evoretail_active_session_id', newId);
    setMessages([
      {
        id: `welcome_${Date.now()}`,
        role: 'assistant',
        content:
          '您好！我是惠普官方旗舰店金牌售前顾问【智小惠】。\n本店全线笔记本均享官方正品保障与全国联保，支持自行开盖加装固态与内存且不破坏整机质保。请问您平时选购电脑的主要用途是硬核 3A 电竞、4K 视频创作还是出差商务办公呢？',
        meta: { prompt_version: 'v2.0.0', llm_mode: 'live' },
      },
    ]);
    setSelectedSpu(null);
    setCurrentProduct(null);
    Message.success('已开启新咨询会话');
    fetchSessions();
  };

  // 1. 获取商品主数据与版本并恢复历史会话
  useEffect(() => {
    document.title = '惠普官方 3C 智能顾问 · 智小惠 - 自进化售前咨询客服系统';
    fetch(`${API_BASE}/products/list`)
      .then((res) => res.json())
      .then((res) => {
        if (res.code === 200 && res.data) {
          setProducts(res.data);
          // 默认全店导购顾问态，selectedSpu 为 null
          setSelectedSpu(null);
          setCurrentProduct(null);
        }
      })
      .catch((err) => {
        console.warn('获取商品列表失败:', err);
      });

    fetchVersions();
    fetchSessions();

    // 尝试恢复当前活跃会话历史记录
    const savedSessionId = localStorage.getItem('evoretail_active_session_id');
    if (savedSessionId) {
      loadSessionHistory(savedSessionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. 切换选中的 SPU 或切回全店通用模式
  const handleSelectProduct = (product: ProductItem | null) => {
    if (!product) {
      setSelectedSpu(null);
      setCurrentProduct(null);
      setMessages((prev) => [
        ...prev,
        {
          id: `switch_${Date.now()}`,
          role: 'assistant',
          content:
            '已为您切回【惠普官方旗舰店 · 全能售前导购总窗口】！\n您可以自由询问全店任意机型、跨品横向比对、按预算筛选推荐或咨询全国联保售后政策。',
          meta: {
            prompt_version: 'v2.0.0',
            llm_mode: 'live',
          },
        },
      ]);
      return;
    }

    setSelectedSpu(product.spu_code);
    setCurrentProduct(product);

    const isIntegrated =
      product.specs?.hardware?.gpu?.includes('核显') ||
      product.specs?.hardware?.gpu?.includes('集成') ||
      product.specs?.hardware?.gpu?.includes('Iris') ||
      product.specs?.hardware?.gpu?.includes('Arc') ||
      product.specs?.hardware?.gpu?.includes('Radeon');
    const gpuDesc = isIntegrated
      ? `${product.specs?.hardware?.gpu} (${product.specs?.hardware?.tgp_watt}W 核心能效)`
      : `${product.specs?.hardware?.gpu} (${product.specs?.hardware?.tgp_watt}W 满血)`;
    const slotDesc =
      (product.specs?.hardware?.m2_slots_total ?? 0) >= 2 ? `双 M.2 扩展插槽` : `单 M.2 固态插槽`;

    setMessages((prev) => [
      ...prev,
      {
        id: `switch_${Date.now()}`,
        role: 'assistant',
        content: `已为您定位至【${product.title}】单品参考态！\n官方指导价 ¥${product.official_price}，搭载 ${gpuDesc}，配备 ${slotDesc}。您可以针对这款机型提问，也可以随时询问全店其它机型或进行对比！`,
        meta: {
          prompt_version: 'v2.0.0',
          llm_mode: 'live',
        },
      },
    ]);
  };

  // 滚动至底
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // 3. 复制文本辅助函数
  const handleCopyText = (text: string) => {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text);
      Message.success('已复制回复内容到剪贴板');
    }
  };

  // 4. 发送买家咨询并处理 SSE 流式传输
  const handleSendMessage = async (queryText?: string) => {
    const textToSend = (queryText || inputVal).trim();
    if (!textToSend || isGenerating) return;

    setInputVal('');

    const userMsgId = `user_${Date.now()}`;
    const assistantMsgId = `ai_${Date.now()}`;

    const newHistory = messages
      .filter((m) => m.id !== 'welcome' && !m.id.startsWith('switch_'))
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: textToSend },
      { id: assistantMsgId, role: 'assistant', content: '', isStreaming: true },
    ]);

    setIsGenerating(true);

    try {
      const response = await fetch(`${API_BASE}/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          spu_code: selectedSpu || undefined,
          query: textToSend,
          history: newHistory,
        }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`网络响应异常: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let partialChunk = '';
      let accumulatedText = '';
      let metaInfo: any = null;
      const collectedToolCalls: Array<{ tool_name: string; arguments: any; cost_ms?: number }> = [];

      // eslint-disable-next-line no-constant-condition
      while (true) {
        // eslint-disable-next-line no-await-in-loop
        const { value, done } = await reader.read();
        if (done) break;

        partialChunk += decoder.decode(value, { stream: true });
        const lines = partialChunk.split('\n\n');
        partialChunk = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const dataStr = line.slice(6).trim();
          if (dataStr === '[DONE]') continue;

          try {
            const dataObj = JSON.parse(dataStr);
            if (dataObj.type === 'chunk' && dataObj.content) {
              accumulatedText += dataObj.content;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        content: accumulatedText,
                        isStreaming: true,
                        toolCalls: [...collectedToolCalls],
                      }
                    : m
                )
              );
            } else if (dataObj.type === 'tool_call') {
              collectedToolCalls.push({
                tool_name: dataObj.tool_name,
                arguments: dataObj.arguments,
                cost_ms: dataObj.cost_ms,
              });
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsgId ? { ...m, toolCalls: [...collectedToolCalls] } : m
                )
              );
            } else if (dataObj.type === 'meta') {
              metaInfo = dataObj;
            }
          } catch (e) {
            console.error('SSE JSON 解析错误:', e);
          }
        }
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: accumulatedText,
                isStreaming: false,
                toolCalls: [...collectedToolCalls],
                meta: metaInfo || { prompt_version: 'v2.0.0', cost_ms: 120 },
              }
            : m
        )
      );
    } catch (err: any) {
      Message.error(`服务通信失败: ${err.message}`);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: `抱歉，客服服务暂时遇到网络波动 (${err.message})，请确认后端已正常启动。`,
                isStreaming: false,
              }
            : m
        )
      );
    } finally {
      setIsGenerating(false);
      fetchSessions();
    }
  };

  // 5. 触发沙箱回归
  const handleRunSandbox = async () => {
    setIsRunningSandbox(true);
    try {
      const res = await fetch(`${API_BASE}/evolution/run-sandbox`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ concurrency: 20, sample_size: 50 }),
      });
      const data = await res.json();
      if (data.code === 200) {
        setSandboxReport(data.data);
        Message.success(
          `沙箱 500 道金标回归跑分完成！得分: ${data.data.overall_score}，门禁: ${data.data.action}`
        );
      }
    } catch (e: any) {
      Message.error(`沙箱执行异常: ${e.message}`);
    } finally {
      setIsRunningSandbox(false);
    }
  };

  // 6. 触发 Critic 流失诊断
  const handleDiagnose = async () => {
    try {
      const res = await fetch(`${API_BASE}/evolution/diagnose`, { method: 'POST' });
      const data = await res.json();
      if (data.code === 200) {
        setDiagnoseReport(data.data);
        Message.info('Critic 会话流失归因诊断分析已就绪！');
      }
    } catch (e: any) {
      Message.error(`诊断请求失败: ${e.message}`);
    }
  };

  // 7. 版本秒级回滚
  const handleRollback = async (targetVer: string) => {
    try {
      const res = await fetch(`${API_BASE}/evolution/rollback`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Token': (window as any).ADMIN_TOKEN || 'dev-secret-admin-token-2024',
        },
        body: JSON.stringify({ target_version: targetVer }),
      });
      const data = await res.json();
      if (data.code === 200) {
        Message.success(data.data.message);
        fetchVersions();
      }
    } catch (e: any) {
      Message.error(`回滚操作失败: ${e.message}`);
    }
  };

  // 8. 触发一键自进化优化
  const handleOptimize = async () => {
    setIsOptimizing(true);
    try {
      const res = await fetch(`${API_BASE}/evolution/optimize`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Token': (window as any).ADMIN_TOKEN || 'dev-secret-admin-token-2024',
        },
      });
      const data = await res.json();
      if (data.code === 200 && data.data) {
        Message.success(
          `自进化优化完成！候选版本: ${data.data.candidate_version || ''}，状态: ${
            data.data.status
          }`
        );
        fetchVersions();
      } else {
        Message.warning(`自进化未通过门禁: ${data.message || data.data?.reason || '未达标'}`);
      }
    } catch (e: any) {
      Message.error(`自进化生成异常: ${e.message}`);
    } finally {
      setIsOptimizing(false);
    }
  };

  // 快捷常见咨询建议词（支持全店通用模式与单品模式自适应）
  const quickFaqList = currentProduct
    ? [
        '这款能自己加装第二根固态吗？支持多大？',
        '显卡满血释放功耗是多少瓦？支持独显直连吗？',
        '平时玩 3A 游戏发热烫手严重吗？散热表现如何？',
        '默认发什么快递？今天买什么时候能发货？',
        '现在下单有什么赠品活动？晒单怎么领大礼包？',
      ]
    : [
        '战66五代和光影精灵16怎么选？差价多少？',
        '预算 5000 元以内，平时剪辑视频+兼顾轻薄便携，推荐哪款？',
        '暗影精灵10旗舰版不插电能跑满血独显吗？续航如何？',
        '店里哪款轻薄本带雷电4接口，屏幕是高色域高刷的？',
        '自己在家里拆机加装固态硬盘和内存条会破坏整机保修吗？',
      ];

  const activePromptVersion =
    versionList.find((v: any) => v.is_active)?.version ||
    sandboxReport?.candidate_version ||
    'v2.0.0';

  const latestAssistantWithMode = [...messages]
    .reverse()
    .find((m) => m.role === 'assistant' && m.meta?.llm_mode);
  const currentModeLabel =
    latestAssistantWithMode?.meta?.llm_mode === 'live'
      ? 'Live 大模型驱动'
      : latestAssistantWithMode?.meta?.llm_mode === 'cache'
      ? 'Cache 本地高速缓存驱动'
      : latestAssistantWithMode?.meta?.llm_mode === 'fallback'
      ? 'Fallback 降级兜底模式'
      : latestAssistantWithMode?.meta?.llm_mode === 'mock'
      ? 'Mock 规则模式'
      : 'Live 大模型驱动';

  return (
    <div className={styles.workspaceWrapper}>
      {/* 顶部极简毛玻璃导航条 */}
      <header className={styles.glassHeader}>
        <div className={styles.brandCluster}>
          <div className={styles.brandBadgeIcon}>HP</div>
          <div className={styles.titleGroup}>
            <h1>
              惠普官方 3C 智能顾问 · 智小惠
              <span style={{ fontSize: 11, fontWeight: 500, color: '#165dff' }}>
                {activePromptVersion}
              </span>
            </h1>
            <p className={styles.subSubtitle}>
              <span className={styles.liveDot} />
              官方正品咨询台 · {currentModeLabel}
            </p>
          </div>
        </div>

        <div className={styles.headerMetaBadges}>
          <span className={`${styles.pillBadge} ${styles.secure}`}>🛡️ Pydantic v2 事实防幻觉</span>
          <span className={`${styles.pillBadge} ${styles.highlight}`}>
            ⚡ BM25 + Chroma 本地混合知识库
          </span>
          <Button
            size="small"
            type="text"
            status="danger"
            onClick={handleCreateNewSession}
          >
            ➕ 新建咨询会话
          </Button>
        </div>
      </header>

      {/* 主三栏通透工作台 */}
      <div className={styles.threeColumnLayout}>
        {/* ==========================================================================
            左栏：3C 商品画廊导航与历史会话抽屉
            ========================================================================== */}
        <aside className={styles.leftGalleryColumn}>
          {/* 顶栏 Tab 切换：在售展台 vs 历史会话 */}
          <div className={styles.tabSwitchBar}>
            <button
              className={`${styles.switchBtn} ${leftTab === 'gallery' ? styles.activeSwitch : ''}`}
              onClick={() => setLeftTab('gallery')}
            >
              💻 在售展台
            </button>
            <button
              className={`${styles.switchBtn} ${leftTab === 'history' ? styles.activeSwitch : ''}`}
              onClick={() => {
                setLeftTab('history');
                fetchSessions();
              }}
            >
              🕒 咨询历史 {sessions.length > 0 && `(${sessions.length})`}
            </button>
          </div>

          {/* 新建咨询会话快捷按钮 */}
          <button className={styles.newSessionBtn} onClick={handleCreateNewSession}>
            ➕ 开启新咨询会话
          </button>

          {leftTab === 'gallery' ? (
            <>
              <div className={styles.columnHeader}>
                <h3>3C 笔记本在售展台</h3>
                <span className={styles.itemCount}>{products.length} 款机型</span>
              </div>

              <div className={styles.productListScroll}>
                {/* 全店通用导购入口 */}
                <div
                  className={`${styles.productCard} ${selectedSpu === null ? styles.activeCard : ''}`}
                  onClick={() => handleSelectProduct(null)}
                  style={{
                    borderLeft: selectedSpu === null ? '3px solid #165DFF' : '3px solid transparent',
                    background: selectedSpu === null ? 'rgba(22,93,255,0.08)' : undefined,
                    marginBottom: 8,
                  }}
                >
                  <div className={styles.cardTopRow}>
                    <span className={styles.cardTitle} style={{ fontWeight: 600 }}>
                      🏪 惠普全店官方售前顾问
                    </span>
                    <Tag size="small" color="arcoblue">
                      全店通用
                    </Tag>
                  </div>

                  <div className={styles.specTagsWrapper}>
                    <span className={`${styles.miniTag} ${styles.highlightTag}`}>全店 10 款机型</span>
                    <span className={styles.miniTag}>跨品比对</span>
                    <span className={styles.miniTag}>预算推荐</span>
                  </div>
                </div>

                {products.map((p) => {
                  const isSelected = p.spu_code === selectedSpu;
                  return (
                    <div
                      key={p.spu_code}
                      className={`${styles.productCard} ${isSelected ? styles.activeCard : ''}`}
                      onClick={() => handleSelectProduct(p)}
                    >
                      <div className={styles.cardTopRow}>
                        <span className={styles.cardTitle}>{p.title}</span>
                        <span className={styles.priceTag}>¥{p.official_price}</span>
                      </div>

                      <div className={styles.specTagsWrapper}>
                        <span className={`${styles.miniTag} ${styles.highlightTag}`}>
                          {p.specs?.hardware?.gpu} ({p.specs?.hardware?.tgp_watt}W)
                        </span>
                        <span className={styles.miniTag}>
                          {p.specs?.hardware?.m2_slots_total} 个 M.2 槽位
                        </span>
                        <span className={styles.miniTag}>
                          {p.specs?.display?.refresh_rate}Hz {p.specs?.display?.resolution}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            <>
              <div className={styles.columnHeader}>
                <h3>历史咨询会话记录</h3>
                <span className={styles.itemCount}>{sessions.length} 个会话</span>
              </div>

              <div className={styles.historyListScroll}>
                {sessions.length === 0 ? (
                  <div
                    style={{
                      textAlign: 'center',
                      color: '#86909c',
                      fontSize: 12,
                      padding: '40px 10px',
                      lineHeight: 1.6,
                    }}
                  >
                    暂无历史咨询会话
                    <br />
                    在下方输入框提问即可自动保存
                  </div>
                ) : (
                  sessions.map((s) => {
                    const isActive = s.session_id === sessionId;
                    return (
                      <div
                        key={s.session_id}
                        className={`${styles.sessionCard} ${
                          isActive ? styles.activeSessionCard : ''
                        }`}
                        onClick={() => handleSwitchSession(s.session_id, s.spu_code)}
                      >
                        <div className={styles.sessionTitle}>
                          {s.title_summary || '未命名咨询'}
                        </div>
                        <div className={styles.sessionMetaRow}>
                          <span>{s.last_active_at ? s.last_active_at.slice(5, 16) : ''}</span>
                          <Tag size="small" color={isActive ? 'arcoblue' : 'gray'}>
                            {s.message_count} 轮问答
                          </Tag>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </>
          )}

          <div className={styles.leftFooterNote}>
            <span>🛡️ 官方全国联保支持</span>
            <span>无损自行加装质保</span>
          </div>
        </aside>

        {/* ==========================================================================
            中栏：沉浸式客服主对话流
            ========================================================================== */}
        <main className={styles.centerChatColumn}>
          {/* 当前选定咨询 SPU 横幅或全店通用横幅 */}
          {currentProduct ? (
            <div className={styles.activeProductBanner}>
              <div className={styles.bannerLeft}>
                <div className={styles.productIconBadge}>💻</div>
                <div>
                  <span className={styles.bannerTitle}>{currentProduct.title}</span>
                  <div style={{ display: 'flex', gap: 6, marginTop: 2, alignItems: 'center' }}>
                    <Tag size="small" color="arcoblue">
                      {currentProduct.specs?.hardware?.cpu}
                    </Tag>
                    <Tag size="small" color="cyan">
                      {currentProduct.specs?.hardware?.gpu?.includes('核显') ||
                      currentProduct.specs?.hardware?.gpu?.includes('集成') ||
                      currentProduct.specs?.hardware?.gpu?.includes('Iris') ||
                      currentProduct.specs?.hardware?.gpu?.includes('Arc') ||
                      currentProduct.specs?.hardware?.gpu?.includes('Radeon')
                        ? `${currentProduct.specs?.hardware?.tgp_watt}W 核心能效`
                        : `${currentProduct.specs?.hardware?.tgp_watt}W 满血`}
                    </Tag>
                    <Tag size="small" color="purple">
                      {(currentProduct.specs?.hardware?.m2_slots_total ?? 0) >= 2
                        ? '双固态插槽'
                        : '单 M.2 槽位'}
                    </Tag>
                    <Tag size="small" color="orangered">
                      {(currentProduct.specs?.hardware?.ram_slots ?? 0) >= 2
                        ? '双内存插槽'
                        : '板载内存/单槽'}
                    </Tag>
                    <Button
                      size="mini"
                      type="text"
                      style={{ padding: '0 4px', height: 20, fontSize: 11 }}
                      onClick={() => handleSelectProduct(null)}
                    >
                      ← 切回全店咨询
                    </Button>
                  </div>
                </div>
              </div>
              <div className={styles.bannerRight}>
                <span className={styles.priceHighlight}>
                  官方价 ¥{currentProduct.official_price}
                </span>
              </div>
            </div>
          ) : (
            <div
              className={styles.activeProductBanner}
              style={{ background: '#f2f7ff', borderColor: '#bedaff' }}
            >
              <div className={styles.bannerLeft}>
                <div
                  className={styles.productIconBadge}
                  style={{ background: '#165DFF', color: '#fff' }}
                >
                  🏪
                </div>
                <div>
                  <span className={styles.bannerTitle} style={{ color: '#165DFF' }}>
                    惠普官方旗舰店 · 全能售前导购顾问
                  </span>
                  <div style={{ fontSize: 12, color: '#4e5969', marginTop: 2 }}>
                    💡 支持任意跨机型比对、预算精准筛选推荐、官方售后质保答疑，无任何单品绑定限制
                  </div>
                </div>
              </div>
              <div className={styles.bannerRight}>
                <Tag color="blue" size="medium">
                  自由咨询模式
                </Tag>
              </div>
            </div>
          )}

          {/* 消息滚动流 */}
          <div className={styles.messageScrollContainer}>
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`${styles.chatMessageItem} ${
                  msg.role === 'user' ? styles.userItem : styles.assistantItem
                }`}
              >
                <div className={styles.avatarBubble}>{msg.role === 'user' ? '👤' : '🤖'}</div>
                <div className={styles.bubbleColumn}>
                  {msg.role === 'assistant' && msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                      {msg.toolCalls.map((tc, idx) => (
                        <Tag key={idx} size="small" color="arcoblue" style={{ borderRadius: 4 }}>
                          🔧 已调用工具：<code>{tc.tool_name}</code>
                          {tc.cost_ms !== undefined && ` (${tc.cost_ms}ms)`}
                        </Tag>
                      ))}
                    </div>
                  )}
                  <div className={styles.speechBubble}>
                    {msg.content}
                    {msg.isStreaming && <span className={styles.typingCursor} />}
                  </div>

                  {msg.role === 'assistant' && msg.meta && (
                    <div className={styles.messageMetaRow}>
                      <span className={styles.auditVerified}>
                        {msg.meta.llm_mode === 'live'
                          ? '🟢 Live 大模型驱动'
                          : msg.meta.llm_mode === 'cache'
                          ? '⚡ Cache 缓存模式'
                          : msg.meta.llm_mode === 'fallback'
                          ? '🟠 Fallback 降级模式'
                          : '🔵 Mock 规则模式'}
                      </span>
                      <span>Prompt: {msg.meta.prompt_version || activePromptVersion}</span>
                      {msg.meta.trace_id && <span>Trace: {msg.meta.trace_id}</span>}
                      {msg.meta.is_cached && (
                        <span className={styles.cacheBadge}>⚡ 本地高速缓存</span>
                      )}
                      {msg.meta.cost_ms !== undefined && <span>耗时: {msg.meta.cost_ms}ms</span>}
                      {msg.meta.output_tokens !== undefined && (
                        <span className={styles.tokenBadge}>
                          🔤 回复: {msg.meta.output_tokens} Tokens
                          {msg.meta.total_tokens !== undefined &&
                            ` (总: ${msg.meta.total_tokens})`}
                        </span>
                      )}
                      <button
                        className={styles.copyActionBtn}
                        onClick={() => handleCopyText(msg.content)}
                      >
                        复制
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messageEndRef} />
          </div>

          {/* 胶囊快捷常见问答建议词 */}
          <div className={styles.quickSuggestionStrip}>
            <span className={styles.stripLabel}>快捷提问：</span>
            {quickFaqList.map((faq, idx) => (
              <button
                key={idx}
                className={styles.pillChip}
                disabled={isGenerating}
                onClick={() => handleSendMessage(faq)}
              >
                {faq}
              </button>
            ))}
          </div>

          {/* 底部输入舱 */}
          <div className={styles.chatInputDock}>
            <TextArea
              className={styles.inputField}
              placeholder="向官方顾问咨询配置、满血功耗、加装固态、顺丰发货或晒单赠品... (Enter 发送)"
              value={inputVal}
              onChange={(v) => setInputVal(v)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  handleSendMessage();
                }
              }}
              autoSize={{ minRows: 2, maxRows: 4 }}
              disabled={isGenerating}
            />
            <Button
              className={styles.sendActionBtn}
              type="primary"
              loading={isGenerating}
              onClick={() => handleSendMessage()}
            >
              发送咨询
            </Button>
          </div>
        </main>

        {/* ==========================================================================
            右栏：双 Tab 智能切换工作台 (规格全景 vs 进化工坊沙箱)
            ========================================================================== */}
        <aside
          className={`${styles.rightDashboardColumn} ${rightCollapsed ? styles.collapsed : ''}`}
        >
          {/* 头部 Tab 切换与收起按钮 */}
          <div className={styles.panelHeader}>
            {!rightCollapsed && (
              <div className={styles.tabSegmentGroup}>
                <button
                  className={`${styles.segmentBtn} ${
                    rightTab === 'facts' ? styles.activeSegment : ''
                  }`}
                  onClick={() => setRightTab('facts')}
                >
                  ⚙️ 硬件事实
                </button>
                <button
                  className={`${styles.segmentBtn} ${
                    rightTab === 'sandbox' ? styles.activeSegment : ''
                  }`}
                  onClick={() => setRightTab('sandbox')}
                >
                  📊 进化工坊
                </button>
              </div>
            )}
            <Tooltip content={rightCollapsed ? '展开右栏' : '收起右栏'}>
              <button
                className={styles.collapseToggleBtn}
                onClick={() => setRightCollapsed(!rightCollapsed)}
              >
                {rightCollapsed ? '◀' : '▶'}
              </button>
            </Tooltip>
          </div>

          {/* 面板内容区 */}
          {!rightCollapsed && (
            <div className={styles.panelBody}>
              {rightTab === 'facts' && currentProduct && (
                <>
                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>核心性能释放 (TGP)</span>
                      <Tag
                        color={
                          currentProduct.specs.hardware.gpu.includes('核显') ||
                          currentProduct.specs.hardware.gpu.includes('集成') ||
                          currentProduct.specs.hardware.gpu.includes('Iris') ||
                          currentProduct.specs.hardware.gpu.includes('Arc') ||
                          currentProduct.specs.hardware.gpu.includes('Radeon')
                            ? 'blue'
                            : 'red'
                        }
                      >
                        {currentProduct.specs.hardware.gpu.includes('核显') ||
                        currentProduct.specs.hardware.gpu.includes('集成') ||
                        currentProduct.specs.hardware.gpu.includes('Iris') ||
                        currentProduct.specs.hardware.gpu.includes('Arc') ||
                        currentProduct.specs.hardware.gpu.includes('Radeon')
                          ? `${currentProduct.specs.hardware.tgp_watt}W 核心能效`
                          : `${currentProduct.specs.hardware.tgp_watt}W 满血释放`}
                      </Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        { label: '处理器 CPU', value: currentProduct.specs.hardware.cpu },
                        { label: '显卡规格', value: currentProduct.specs.hardware.gpu },
                        {
                          label: '裸机净重',
                          value: `${currentProduct.specs.hardware.weight_kg} kg`,
                        },
                      ]}
                    />
                    <div style={{ marginTop: 10 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: 11,
                          marginBottom: 2,
                        }}
                      >
                        <span>功耗释放水平</span>
                        <strong>{currentProduct.specs.hardware.tgp_watt}W</strong>
                      </div>
                      <Progress
                        percent={Math.min(
                          100,
                          Math.round((currentProduct.specs.hardware.tgp_watt / 175) * 100)
                        )}
                        status="success"
                      />
                    </div>
                  </div>

                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>扩展槽位 (防幻觉重点)</span>
                      <Tag color="arcoblue">
                        {currentProduct.specs.hardware.m2_slots_total >= 2
                          ? '双固态'
                          : '单 M.2 固态'}{' '}
                        + {currentProduct.specs.hardware.ram_slots >= 2 ? '双内存' : '板载/单槽'}
                      </Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        {
                          label: 'M.2 固态槽位',
                          value:
                            currentProduct.specs.hardware.m2_slots_total >= 2
                              ? `${currentProduct.specs.hardware.m2_slots_total} 个 (双固态位，支持加装第二根)`
                              : `${currentProduct.specs.hardware.m2_slots_total} 个 (单槽，仅支持替换升级，无第二插槽)`,
                        },
                        {
                          label: '标配固态硬盘',
                          value: currentProduct.specs.hardware.storage_installed,
                        },
                        {
                          label: '内存插槽数量',
                          value:
                            currentProduct.specs.hardware.ram_slots >= 2
                              ? `${currentProduct.specs.hardware.ram_slots} 个插槽 (最大拓展 ${currentProduct.specs.hardware.ram_max_gb}G)`
                              : `板载/单内存 (最大 ${currentProduct.specs.hardware.ram_max_gb}G，不支持插槽加装)`,
                        },
                        {
                          label: '标配内存容量',
                          value: currentProduct.specs.hardware.ram_installed,
                        },
                        {
                          label: '雷电4 接口',
                          value: currentProduct.specs.hardware.thunderbolt_port
                            ? '搭载雷电4 (支持 100W PD 快充与显卡坞)'
                            : '未配备雷电4 (配备标准高速 Type-C)',
                        },
                      ]}
                    />
                  </div>

                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>电竞高刷屏素质</span>
                      <Tag color="purple">{currentProduct.specs.display.refresh_rate}Hz</Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        {
                          label: '屏幕尺寸',
                          value: `${currentProduct.specs.display.screen_size} 英寸`,
                        },
                        { label: '屏幕分辨率', value: currentProduct.specs.display.resolution },
                        {
                          label: '高刷率',
                          value: `${currentProduct.specs.display.refresh_rate} Hz`,
                        },
                        {
                          label: '色域与亮度',
                          value: `${currentProduct.specs.display.color_gamut} | ${
                            currentProduct.specs.display.brightness_nits || 300
                          } nits`,
                        },
                      ]}
                    />
                  </div>

                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>促销赠品与全国联保</span>
                    </div>
                    <p style={{ margin: 0, fontSize: 12, color: '#4e5969', lineHeight: 1.6 }}>
                      🎁 <strong>赠品政策：</strong>
                      {currentProduct.specs.gift_policy}
                    </p>
                    <p style={{ margin: '6px 0 0', fontSize: 12, color: '#00b42a' }}>
                      🛡️ <strong>全国联保：</strong>2 年官方联保，支持自行开盖无损保修。
                    </p>
                  </div>
                </>
              )}

              {rightTab === 'facts' && !currentProduct && (
                <div className={styles.glassCard}>
                  <div className={styles.cardHeaderLabel}>
                    <span>惠普官方在售机型全景速查</span>
                    <Tag color="arcoblue">全店 10 款</Tag>
                  </div>
                  <p style={{ fontSize: 12, color: '#4e5969', lineHeight: 1.6, margin: '0 0 10px' }}>
                    当前处于<strong>全店通用咨询模式</strong>。您可以在中栏直接询问任意跨机型对比、预算推荐或硬件参数。点击下方机型亦可快速切换至单品详细规格看板：
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 440, overflowY: 'auto' }}>
                    {products.map((p) => (
                      <div
                        key={p.spu_code}
                        onClick={() => handleSelectProduct(p)}
                        style={{
                          padding: '8px 10px',
                          borderRadius: 6,
                          background: '#f7f8fa',
                          cursor: 'pointer',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                          fontSize: 12,
                          border: '1px solid #e5e6eb',
                        }}
                      >
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          <span style={{ fontWeight: 500, color: '#1d2129' }}>{p.title}</span>
                          <span style={{ fontSize: 11, color: '#86909c' }}>
                            {p.specs?.hardware?.cpu} | {p.specs?.hardware?.gpu} | {p.specs?.hardware?.weight_kg}kg
                          </span>
                        </div>
                        <span style={{ fontWeight: 600, color: '#f53f3f' }}>¥{p.official_price}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ marginTop: 12, fontSize: 12, color: '#00b42a' }}>
                    🛡️ 全店政策：全线机型均享 2 年官方全国联保，支持自行开盖加装固态/内存不脱保。
                  </div>
                </div>
              )}

              {rightTab === 'sandbox' && (
                <>
                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>激活态 Prompt 状态</span>
                      <Tag color="green">{activePromptVersion} Active</Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        { label: '1000 Token 账户', value: '400人设+画像 / 300事实 / 300历史' },
                        { label: '数值护栏实测', value: '反例拦截率 100% (误杀率 0%)' },
                        { label: '混合知识库', value: 'BM25 专有名词 + Chroma BGE 向量' },
                      ]}
                    />
                    <div style={{ marginTop: 12, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      <Button
                        size="mini"
                        type="primary"
                        loading={isOptimizing}
                        onClick={handleOptimize}
                      >
                        ✨ 一键生成补丁并沙箱演进
                      </Button>
                      <Button size="mini" type="outline" onClick={handleDiagnose}>
                        🔍 Critic 流失诊断
                      </Button>
                      <Select
                        size="mini"
                        style={{ width: 140 }}
                        placeholder="回滚版本"
                        onChange={(v) => handleRollback(v)}
                      >
                        {versionList.map((ver: any) => (
                          <Select.Option key={ver.version} value={ver.version}>
                            {ver.version} {ver.is_active ? '(当前激活)' : `(${ver.eval_score}分)`}
                          </Select.Option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  {diagnoseReport && (
                    <div className={styles.glassCard}>
                      <div className={styles.cardHeaderLabel}>
                        <span>Critic 会话诊断归因</span>
                        <span style={{ fontSize: 11, color: '#86909c' }}>
                          样本数: {diagnoseReport.total_analyzed}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                        <Tag size="small" color="orange">
                          价格犹豫: {diagnoseReport.loss_categories?.PRICE_HESITATION}
                        </Tag>
                        <Tag size="small" color="blue">
                          性能疑虑: {diagnoseReport.loss_categories?.HARDWARE_UNCERTAINTY}
                        </Tag>
                        <Tag size="small" color="purple">
                          缺少促单: {diagnoseReport.loss_categories?.SPIN_MISSED_RECOMMENDATION}
                        </Tag>
                        <Tag size="small" color="green">
                          顺畅转化: {diagnoseReport.loss_categories?.SMOOTH_CONVERSION}
                        </Tag>
                      </div>
                      <p style={{ margin: 0, fontSize: 11.5, color: '#165dff' }}>
                        💡 <strong>建议补丁：</strong>
                        {diagnoseReport.actionable_prompt_recommendations?.[0]}
                      </p>
                    </div>
                  )}

                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>500 道金标评测沙箱</span>
                      <span style={{ fontSize: 11, color: '#86909c' }}>门禁线: 95.0分</span>
                    </div>

                    <div style={{ marginBottom: 10 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: 11,
                          marginBottom: 2,
                        }}
                      >
                        <span>硬件参数绝对断言 (40%)</span>
                        <strong style={{ color: '#00b42a' }}>
                          {sandboxReport?.breakdown?.hardware_assert_pass_rate !== undefined
                            ? `${sandboxReport.breakdown.hardware_assert_pass_rate}% 通过`
                            : '待运行'}
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.hardware_assert_pass_rate ?? 0}
                        status="success"
                      />
                    </div>

                    <div style={{ marginBottom: 10 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: 11,
                          marginBottom: 2,
                        }}
                      >
                        <span>平台合规风控红线 (20%)</span>
                        <strong style={{ color: '#00b42a' }}>
                          {sandboxReport?.breakdown?.risk_control_pass_rate !== undefined
                            ? `${sandboxReport.breakdown.risk_control_pass_rate}% (零违规)`
                            : '待运行'}
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.risk_control_pass_rate ?? 0}
                        status="success"
                      />
                    </div>

                    <div style={{ marginBottom: 14 }}>
                      <div
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          fontSize: 11,
                          marginBottom: 2,
                        }}
                      >
                        <span>SPIN 促单表现评分 (40%)</span>
                        <strong style={{ color: '#165dff' }}>
                          {sandboxReport?.breakdown?.spin_average_score !== undefined
                            ? `${sandboxReport.breakdown.spin_average_score} 分`
                            : '待运行'}
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.spin_average_score ?? 0}
                        status="normal"
                      />
                    </div>

                    {sandboxReport && (
                      <div
                        style={{
                          padding: '6px 10px',
                          background: '#e8ffea',
                          borderRadius: 6,
                          marginBottom: 12,
                          fontSize: 11.5,
                        }}
                      >
                        <span style={{ color: '#00b42a', fontWeight: 600 }}>
                          ✓ 跑分: {sandboxReport.overall_score} 分 | 违规:{' '}
                          {sandboxReport.zero_tolerance_violations} | 耗时:{' '}
                          {sandboxReport.cost_seconds}s
                        </span>
                      </div>
                    )}

                    <Button
                      type="primary"
                      long
                      loading={isRunningSandbox}
                      onClick={handleRunSandbox}
                    >
                      🚀 触发 500 道金标沙箱高并发回归
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
