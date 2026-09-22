// Chat answer for one employee. Claude when ANTHROPIC_API_KEY is set, otherwise Workers AI.
import Anthropic from "@anthropic-ai/sdk";

const ACTIONS = ["leave", "sick", "cert_work", "cert_income", "data_change", "question"];

function rules(p) {
  return [
    `Ти помічник для працівників компанії ${p.company}. Ти говориш з одним працівником: ${p.name}.`,
    "Правила відповіді:",
    "- Відповідай українською мовою. Пиши коротко і просто: одне-п'ять речень або короткий список.",
    "- Бери факти тільки з розділу ДАНІ. Не вигадуй суми, дати, строки виплат, правила компанії чи назви документів.",
    "- Якщо відповіді немає в даних, скажи це прямо і запропонуй запит до HR або бухгалтерії.",
    "- Загальні ставки можна пояснювати: ПДФО 18 %, військовий збір 5 %, ЄСВ 22 % платить роботодавець зверху, працівник його не сплачує.",
    "- Суми пиши так: 25 000,00 грн. Дати пиши так: 15.03.2021.",
    "- Не показуй коди рядків листка, якщо працівник про них не питає.",
    "- Ти не можеш погоджувати відпустки, змінювати дані чи виписувати довідки. Ти можеш запропонувати відповідний запит.",
    "- Коли працівник хоче щось оформити, отримати документ, змінити дані або поставити питання людині, додай у кінці окремий рядок: ДІЯ: код.",
    "  Коди: leave - заява на відпустку; sick - лікарняний; cert_work - довідка з місця роботи; cert_income - довідка про доходи; data_change - зміна особистих даних; question - питання до HR або бухгалтерії.",
    "  У цьому рядку тільки один код. Не пиши цей рядок, якщо дія не потрібна.",
  ].join("\n");
}

export function cleanMessages(list) {
  const msgs = (Array.isArray(list) ? list : [])
    .filter((m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string" && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.slice(0, 4000) }))
    .slice(-16);
  while (msgs.length && msgs[0].role !== "user") msgs.shift();
  const merged = [];
  for (const m of msgs) {
    if (merged.length && merged[merged.length - 1].role === m.role) merged[merged.length - 1].content += "\n\n" + m.content;
    else merged.push(m);
  }
  return merged;
}

function splitAction(text) {
  let action = null;
  const body = String(text || "")
    .replace(/<think>[\s\S]*?<\/think>/g, "")
    .replace(/\s[\u2014\u2013]\s/g, " - ")
    .replace(/^\s*\**ДІЯ\**\s*:\s*\**\s*([a-z_]+)\s*\**\s*$/gim, (_, code) => { if (ACTIONS.includes(code)) action = code; return ""; })
    .trim();
  return { text: body, action };
}

export async function answer(env, p, data, messages, modelOverride) {
  const system = `${rules(p)}\n\nДАНІ\n${data}`;
  if (env.ANTHROPIC_API_KEY && !modelOverride) {
    const client = new Anthropic({ apiKey: env.ANTHROPIC_API_KEY });
    const model = env.CLAUDE_MODEL || "claude-opus-5";
    const resp = await client.beta.messages.create({
      model,
      max_tokens: 4000,
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      output_config: { effort: "medium" },
      system,
      messages,
    });
    if (resp.stop_reason === "refusal") return { text: "Я не можу відповісти на це питання. Поставте його HR через запит.", action: "question", model };
    const text = resp.content.filter((b) => b.type === "text").map((b) => b.text).join("");
    return { ...splitAction(text), model: resp.model || model };
  }
  const model = modelOverride || env.AI_MODEL || "@cf/deepseek-ai/deepseek-v4-flash-0731";
  const r = await env.AI.run(model, { messages: [{ role: "system", content: system }, ...messages], max_tokens: 2500, temperature: 0.2 });
  const text = typeof r?.response === "string" ? r.response : r?.choices?.[0]?.message?.content ?? "";
  return { ...splitAction(text), model };
}
