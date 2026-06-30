// Central icon system — Phosphor, brand-tinted (duotone).
// One place to change weight/color globally. UI icons inherit currentColor;
// category icons default to brand sage. Existing envelopes store an emoji
// string, so EMOJI_TO_TOKEN auto-upgrades them to icons with no DB migration.
import {
  ChartBar, Envelope, Receipt, HandCoins, ArrowsClockwise, GearSix,
  Bell, Sun, Moon, CaretDown, Plus, Fire, Sparkle, Money, ShoppingCart,
  CheckCircle, Lock, UsersThree, Target, PiggyBank, Wallet, SignOut, ShieldCheck,
  Warning, Trophy, TelegramLogo, X,
  // categories
  ForkKnife, Coffee, Car, Bus, House, Lightning, WifiHigh, ShoppingBag,
  TShirt, Heartbeat, GraduationCap, BookOpen, CreditCard, FilmSlate,
  GameController, Gift, HandHeart, DeviceMobile, Lifebuoy, Folder,
  Package, Baby, PawPrint, Barbell, Airplane,
} from '@phosphor-icons/react';

const DEFAULT_WEIGHT = 'duotone';
export const BRAND = '#0F6E56';
export const SAVING = '#6366F1';

// Semantic UI / chrome icons
const UI = {
  dashboard: ChartBar,
  envelope: Envelope,
  transaksi: Receipt,
  alokasi: HandCoins,
  langganan: ArrowsClockwise,
  settings: GearSix,
  logout: SignOut,
  admin: ShieldCheck,
  bell: Bell,
  sun: Sun,
  moon: Moon,
  chevron: CaretDown,
  plus: Plus,
  close: X,
  fire: Fire,
  advisor: Sparkle,
  income: Money,
  expense: ShoppingCart,
  check: CheckCircle,
  warning: Warning,
  bolt: Lightning,
  trophy: Trophy,
  telegram: TelegramLogo,
  lock: Lock,
  users: UsersThree,
  target: Target,
  piggy: PiggyBank,
  wallet: Wallet,
};

// Envelope category icons — tokens stored in env.emoji going forward
const CATEGORY = {
  food: ForkKnife, coffee: Coffee, car: Car, bus: Bus, house: House,
  electricity: Lightning, internet: WifiHigh, shopping: ShoppingBag,
  clothes: TShirt, health: Heartbeat, school: GraduationCap, book: BookOpen,
  savings: PiggyBank, bills: Receipt, card: CreditCard, movie: FilmSlate,
  game: GameController, gift: Gift, donation: HandHeart, phone: DeviceMobile,
  emergency: Lifebuoy, folder: Folder, package: Package, baby: Baby,
  pet: PawPrint, sport: Barbell, travel: Airplane, target: Target,
};

// Legacy / picker emoji → category token (auto-upgrade, no migration)
const EMOJI_TO_TOKEN = {
  '🍔': 'food', '🍕': 'food', '🍜': 'food', '🍙': 'food', '🍱': 'food', '🥘': 'food', '🍳': 'food', '🍚': 'food', '🍲': 'food',
  '☕': 'coffee', '🧋': 'coffee',
  '🚗': 'car', '🚙': 'car', '🛵': 'car', '🏍️': 'car', '🏍': 'car', '🚘': 'car',
  '🚌': 'bus', '🚕': 'bus', '🚆': 'bus', '🚊': 'bus',
  '🏠': 'house', '🏡': 'house', '🏘️': 'house',
  '💡': 'electricity', '⚡': 'electricity',
  '🌐': 'internet', '📶': 'internet', '📡': 'internet',
  '🛍️': 'shopping', '🛒': 'shopping',
  '👕': 'clothes', '👗': 'clothes', '🧥': 'clothes', '👔': 'clothes', '👚': 'clothes',
  '💊': 'health', '🏥': 'health', '🩺': 'health', '❤️': 'health', '🩹': 'health',
  '🎓': 'school', '🏫': 'school', '✏️': 'school',
  '📚': 'book', '📖': 'book',
  '🐷': 'savings', '🐖': 'savings', '💰': 'savings', '💵': 'savings', '💸': 'savings',
  '🧾': 'bills', '💳': 'card',
  '🎬': 'movie', '🎥': 'movie', '📺': 'movie',
  '🎮': 'game', '🕹️': 'game',
  '🎁': 'gift', '🎀': 'gift',
  '🤲': 'donation', '🙏': 'donation',
  '📱': 'phone', '☎️': 'phone',
  '🆘': 'emergency', '🚨': 'emergency', '🛟': 'emergency',
  '📁': 'folder', '📂': 'folder', '🗂️': 'folder',
  '📦': 'package',
  '👶': 'baby', '🍼': 'baby',
  '🐱': 'pet', '🐶': 'pet', '🐈': 'pet', '🐕': 'pet',
  '🏃': 'sport', '⚽': 'sport', '🏋️': 'sport', '🚴': 'sport',
  '✈️': 'travel', '🏖️': 'travel', '🧳': 'travel',
  '🎯': 'target',
};

export function Icon({ name, size = 20, weight = DEFAULT_WEIGHT, className = '', color, style }) {
  const Cmp = UI[name] || CATEGORY[name] || Folder;
  return <Cmp size={size} weight={weight} className={className} color={color} style={style} />;
}

// Resolve an envelope's stored icon (token, legacy emoji, or unknown text)
export function EnvelopeIcon({ value, size = 20, weight = DEFAULT_WEIGHT, className = '', color = BRAND, style }) {
  const token = value && (CATEGORY[value] ? value : EMOJI_TO_TOKEN[value]);
  if (token && CATEGORY[token]) {
    const Cmp = CATEGORY[token];
    return <Cmp size={size} weight={weight} className={className} color={color} style={style} />;
  }
  if (value) {
    // Unmapped emoji or custom text — render as-is so nothing breaks
    return <span className={className} style={{ fontSize: size * 0.9, lineHeight: 1, ...style }}>{value}</span>;
  }
  return <Folder size={size} weight={weight} className={className} color={color} style={style} />;
}

export const CATEGORY_TOKENS = Object.keys(CATEGORY);
