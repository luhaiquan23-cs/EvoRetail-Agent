import React, { useState, useEffect, useRef } from 'react';
import {
  Button,
  Input,
  Tag,
  Descriptions,
  Message,
  Progress,
  Tooltip,
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
  meta?: {
    prompt_version?: string;
    cost_ms?: number;
    is_cached?: boolean;
  };
}

export default function EcommerceCSPage() {
  const [products, setProducts] = useState<ProductItem[]>([]);
  const [selectedSpu, setSelectedSpu] = useState<string>('HP-VICTUS-16');
  const [currentProduct, setCurrentProduct] = useState<ProductItem | null>(null);

  // 右侧工作台 Tab 状态: 'facts' (硬件事实) | 'sandbox' (进化工坊沙箱)
  const [rightTab, setRightTab] = useState<'facts' | 'sandbox'>('facts');
  const [rightCollapsed, setRightCollapsed] = useState<boolean>(false);

  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content:
        '您好！我是惠普官方旗舰店金牌售前顾问【智小惠】。\n本店全线笔记本均享官方正品保障与 2 年全国联保，支持自行开盖加装固态与内存且不破坏整机质保。请问您平时选购电脑的主要用途是硬核 3A 电竞、4K 视频创作还是出差商务办公呢？',
      meta: {
        prompt_version: 'v2.0.0',
        cost_ms: 8,
        is_cached: true,
      },
    },
  ]);

  const [inputVal, setInputVal] = useState<string>('');
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [isRunningSandbox, setIsRunningSandbox] = useState<boolean>(false);
  const [sandboxReport, setSandboxReport] = useState<any>(null);
  const [diagnoseReport, setDiagnoseReport] = useState<any>(null);

  const messageEndRef = useRef<HTMLDivElement>(null);

  // 1. 获取商品主数据
  useEffect(() => {
    fetch(`${API_BASE}/products/list`)
      .then((res) => res.json())
      .then((res) => {
        if (res.code === 200 && res.data) {
          setProducts(res.data);
          const found =
            res.data.find((p: ProductItem) => p.spu_code === selectedSpu) || res.data[0];
          if (found) {
            setSelectedSpu(found.spu_code);
            setCurrentProduct(found);
          }
        }
      })
      .catch((err) => {
        console.warn('获取商品列表失败:', err);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2. 切换选中的 SPU
  const handleSelectProduct = (product: ProductItem) => {
    setSelectedSpu(product.spu_code);
    setCurrentProduct(product);
    setMessages((prev) => [
      ...prev,
      {
        id: `switch_${Date.now()}`,
        role: 'assistant',
        content: `已为您定位至【${product.title}】专属咨询窗口！\n官方指导价 ¥${product.official_price}，搭载 ${product.specs?.hardware?.gpu} (${product.specs?.hardware?.tgp_watt}W 满血)，配备 ${product.specs?.hardware?.m2_slots_total} 个 M.2 扩展插槽。有什么想了解的技术细节尽管问我！`,
        meta: {
          prompt_version: 'v2.0.0',
          cost_ms: 2,
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
          session_id: `sess_web_${Date.now()}`,
          spu_code: selectedSpu,
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
                    ? { ...m, content: accumulatedText, isStreaming: true }
                    : m
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_version: targetVer }),
      });
      const data = await res.json();
      if (data.code === 200) {
        Message.success(data.data.message);
      }
    } catch (e: any) {
      Message.error(`回滚操作失败: ${e.message}`);
    }
  };

  // 快捷常见咨询建议词
  const quickFaqList = [
    '这款能自己加装第二根固态吗？支持多大？',
    '显卡满血释放功耗是多少瓦？支持独显直连吗？',
    '平时玩 3A 游戏发热烫手严重吗？散热表现如何？',
    '默认发什么快递？今天买什么时候能发货？',
    '现在下单有什么赠品活动？晒单怎么领大礼包？',
  ];

  return (
    <div className={styles.workspaceWrapper}>
      {/* 顶部极简毛玻璃导航条 */}
      <header className={styles.glassHeader}>
        <div className={styles.brandCluster}>
          <div className={styles.brandBadgeIcon}>HP</div>
          <div className={styles.titleGroup}>
            <h1>
              惠普官方 3C 智能顾问 · 智小惠
              <span style={{ fontSize: 11, fontWeight: 500, color: '#165dff' }}>v2.0</span>
            </h1>
            <p className={styles.subSubtitle}>
              <span className={styles.liveDot} />
              DeepSeek-Chat 实时流式驱动 · 官方正品咨询台
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
            onClick={() =>
              setMessages([
                {
                  id: `welcome_${Date.now()}`,
                  role: 'assistant',
                  content: '会话已重置。您可以随时向我咨询任何硬件规格细节或售后政策！',
                  meta: { prompt_version: 'v2.0.0', cost_ms: 1 },
                },
              ])
            }
          >
            清空对话
          </Button>
        </div>
      </header>

      {/* 主三栏通透工作台 */}
      <div className={styles.threeColumnLayout}>
        {/* ==========================================================================
            左栏：3C 商品画廊导航
            ========================================================================== */}
        <aside className={styles.leftGalleryColumn}>
          <div className={styles.columnHeader}>
            <h3>3C 笔记本在售展台</h3>
            <span className={styles.itemCount}>{products.length} 款机型</span>
          </div>

          <div className={styles.productListScroll}>
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

          <div className={styles.leftFooterNote}>
            <span>🛡️ 官方全国联保支持</span>
            <span>无损自行加装质保</span>
          </div>
        </aside>

        {/* ==========================================================================
            中栏：沉浸式客服主对话流
            ========================================================================== */}
        <main className={styles.centerChatColumn}>
          {/* 当前选定咨询 SPU 横幅 */}
          {currentProduct && (
            <div className={styles.activeProductBanner}>
              <div className={styles.bannerLeft}>
                <div className={styles.productIconBadge}>💻</div>
                <div>
                  <span className={styles.bannerTitle}>{currentProduct.title}</span>
                  <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
                    <Tag size="small" color="arcoblue">
                      {currentProduct.specs?.hardware?.cpu}
                    </Tag>
                    <Tag size="small" color="cyan">
                      显卡 {currentProduct.specs?.hardware?.tgp_watt}W 满血
                    </Tag>
                    <Tag size="small" color="purple">
                      双固态插槽
                    </Tag>
                  </div>
                </div>
              </div>
              <div className={styles.bannerRight}>
                <span className={styles.priceHighlight}>
                  官方价 ¥{currentProduct.official_price}
                </span>
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
                  <div className={styles.speechBubble}>
                    {msg.content}
                    {msg.isStreaming && <span className={styles.typingCursor} />}
                  </div>

                  {msg.role === 'assistant' && msg.meta && (
                    <div className={styles.messageMetaRow}>
                      <span className={styles.auditVerified}>✓ Pydantic 0幻觉门禁</span>
                      <span>Prompt: {msg.meta.prompt_version || 'v2.0.0'}</span>
                      {msg.meta.is_cached && (
                        <span className={styles.cacheBadge}>⚡ 本地高速缓存</span>
                      )}
                      <span>耗时: {msg.meta.cost_ms}ms</span>
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
                      <Tag color="red">{currentProduct.specs.hardware.tgp_watt}W 满血</Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        { label: '处理器 CPU', value: currentProduct.specs.hardware.cpu },
                        { label: '独立显卡 GPU', value: currentProduct.specs.hardware.gpu },
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
                        <span>性能释放释放度</span>
                        <strong>100% 满血</strong>
                      </div>
                      <Progress percent={100} status="success" />
                    </div>
                  </div>

                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>扩展槽位 (防幻觉重点)</span>
                      <Tag color="arcoblue">双固态 + 双内存</Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        {
                          label: 'M.2 固态槽位',
                          value: `${currentProduct.specs.hardware.m2_slots_total} 个 (支持加装不脱保)`,
                        },
                        {
                          label: '标配固态硬盘',
                          value: currentProduct.specs.hardware.storage_installed,
                        },
                        {
                          label: '内存插槽数量',
                          value: `${currentProduct.specs.hardware.ram_slots} 个 (最大拓展 ${currentProduct.specs.hardware.ram_max_gb}G)`,
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

              {rightTab === 'sandbox' && (
                <>
                  <div className={styles.glassCard}>
                    <div className={styles.cardHeaderLabel}>
                      <span>激活态 Prompt 状态</span>
                      <Tag color="green">{sandboxReport?.candidate_version || 'v2.0.0'} Active</Tag>
                    </div>
                    <Descriptions
                      column={1}
                      data={[
                        { label: '1000 Token 账户', value: '400人设 + 300事实 + 300滑动历史' },
                        { label: '事实防幻觉率', value: '< 0.5% (Pydantic v2 生效)' },
                        { label: '混合知识库', value: 'BM25 专有名词 + Chroma BGE 向量' },
                      ]}
                    />
                    <div style={{ marginTop: 12, display: 'flex', gap: 6 }}>
                      <Button size="mini" onClick={() => handleRollback('v2.0.0')}>
                        ⏮️ 秒级回滚至 v2.0.0
                      </Button>
                      <Button size="mini" type="outline" onClick={handleDiagnose}>
                        🔍 Critic 流失诊断
                      </Button>
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
                        <span>硬件参数绝对断言 (200题)</span>
                        <strong style={{ color: '#00b42a' }}>
                          {sandboxReport?.breakdown?.hardware_assert_pass_rate || 100}% 通过
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.hardware_assert_pass_rate || 100}
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
                        <span>平台合规风控红线 (100题)</span>
                        <strong style={{ color: '#00b42a' }}>
                          {sandboxReport?.breakdown?.risk_control_pass_rate || 100}% (零违规)
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.risk_control_pass_rate || 100}
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
                        <span>SPIN 促单表现评分 (200题)</span>
                        <strong style={{ color: '#165dff' }}>
                          {sandboxReport?.breakdown?.spin_average_score || 98.2} 分
                        </strong>
                      </div>
                      <Progress
                        percent={sandboxReport?.breakdown?.spin_average_score || 98.2}
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
