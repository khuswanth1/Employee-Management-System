/** Money for display. Falls back to "1,234.50 XYZ" if the currency code is not one the browser knows. */
export function fmtMoney(amount, currency = 'USD') {
  if (amount == null) return '—'
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount)
  } catch {
    return `${Number(amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`
  }
}

export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
export const monthName = (y, m) => `${MONTHS[m - 1]} ${y}`

export const WARNING = {
  deductions_exceed_pay: 'Deductions are larger than pay',
  no_working_days: 'No working days in this period',
}
export const warningText = (w) => WARNING[w] || (w.startsWith('invalid_calc:') ? `Component ${w.split(':')[1]} has an invalid calculation` : w)

export const CALC = { fixed: 'Fixed amount', percent_of_basic: '% of basic', percent_of_gross: '% of gross pay' }
