from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

class DisplaySpec(BaseModel):
    screen_size: float = Field(..., description="屏幕尺寸(英寸)", ge=12.0, le=20.0)
    resolution: str = Field(..., description="分辨率，如 2.5K (2560x1600)")
    refresh_rate: int = Field(..., description="屏幕刷新率(Hz)", ge=60, le=500)
    color_gamut: str = Field(..., description="色域覆盖，如 100% sRGB")
    brightness_nits: Optional[int] = Field(None, description="亮度(nits)")

class HardwareSpec(BaseModel):
    cpu: str = Field(..., min_length=2, description="处理器型号，如 i7-14700HX")
    gpu: str = Field(..., min_length=2, description="显卡型号，如 RTX 4060")
    tgp_watt: int = Field(..., description="显卡功耗释放(W)", ge=35, le=200)
    ram_installed: str = Field(..., description="标配内存，如 16G DDR5 5600MHz")
    ram_slots: int = Field(..., description="内存插槽总数", ge=1, le=4)
    ram_max_gb: int = Field(..., description="最大支持内存容量(GB)", ge=16, le=128)
    storage_installed: str = Field(..., description="标配固态，如 1TB PCIe 4.0 NVMe")
    m2_slots_total: int = Field(..., description="M.2 固态插槽总数", ge=1, le=4)
    thunderbolt_port: bool = Field(False, description="是否支持雷电4/USB4")
    weight_kg: float = Field(..., description="整机重量(kg)", ge=0.8, le=6.0)

    @field_validator("tgp_watt")
    @classmethod
    def validate_tgp(cls, v: int) -> int:
        if v < 35 or v > 200:
            raise ValueError(f"异常的显卡释放功耗数值: {v}W")
        return v

class ProductItem(BaseModel):
    spu_code: str = Field(..., description="唯一 SPU 编码")
    title: str = Field(..., description="商品完整标题")
    brand: str = Field("HP", description="品牌")
    category: str = Field("游戏笔记本", description="品类")
    official_price: float = Field(..., description="官方指导价")
    display: DisplaySpec
    hardware: HardwareSpec
    sales_pitch: List[str] = Field(default_factory=list, description="推荐销售切入点 (FAB)")
    gift_policy: str = Field("晒单赠电竞双肩包+有线鼠标", description="当前促销赠品")

    def to_anchor_fact(self) -> str:
        """生成不可颠覆的 System Prompt 规格锚定块，供大模型作为绝对事实依据"""
        pitches = "；".join(self.sales_pitch) if self.sales_pitch else ""
        tb_desc = (
            "搭载雷电4接口 (支持 100W PD 快充与支持外接显卡坞)"
            if self.hardware.thunderbolt_port
            else "未配备雷电4接口，采用标准 Type-C 高速接口"
        )
        return (
            f"【咨询商品规格事实（绝对权威，严禁违背或编造）】\n"
            f"- 商品名称: {self.title} (SPU: {self.spu_code})\n"
            f"- 官方售价: ¥{self.official_price:.2f}\n"
            f"- 核心配置: CPU={self.hardware.cpu} | 显卡={self.hardware.gpu} ({self.hardware.tgp_watt}W 满血释放)\n"
            f"- 屏幕素质: {self.display.screen_size}英寸 | {self.display.resolution} | {self.display.refresh_rate}Hz高刷 | {self.display.color_gamut} | 亮度={self.display.brightness_nits or 300}nits高亮防眩光\n"
            f"- 扩展性: 双内存插槽={self.hardware.ram_slots}个(大满贯扩展，标配 {self.hardware.ram_installed}，最大支持 {self.hardware.ram_max_gb}G) | 双 M.2 固态插槽={self.hardware.m2_slots_total}个(支持加装扩展第二根固态，标配 {self.hardware.storage_installed})\n"
            f"- 接口与重量: 接口={tb_desc} | 裸机重量={self.hardware.weight_kg}kg全金属轻薄机身\n"
            f"- 特色亮点: {pitches}\n"
            f"- 赠品与保障: {self.gift_policy}，全国联保支持自行加装无损保修。\n"
        )

