import type { ReactNode } from 'react'

export function BotanicalDecoration() {
  return <svg className="dashboard-botanical" viewBox="0 0 420 280" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <path d="M200 288C198 225 216 168 273 104M213 225C166 209 147 164 133 123M239 164C296 159 322 119 330 77M271 107C279 60 305 45 328 27M211 219C255 227 283 210 309 185" stroke="#426c52" strokeWidth="2.2" strokeLinecap="round"/>
    <g fill="#719678" fillOpacity=".48" stroke="#426c52" strokeOpacity=".44">
      <path d="M269 108C224 102 216 76 220 51c29 9 46 24 49 57ZM277 104c6-35 30-55 58-56-6 30-22 51-58 56ZM241 163c-41-2-60-27-65-54 31 3 55 18 65 54ZM248 160c8-34 34-56 63-58-6 30-24 49-63 58ZM205 214c-35-12-48-41-46-67 30 11 47 31 46 67ZM216 220c18-33 42-43 68-40-13 28-34 43-68 40ZM311 185c0-27 13-46 35-54 5 28-6 47-35 54Z"/>
      <path d="M330 75c-21-19-25-39-17-57 21 13 28 32 17 57ZM331 79c9-25 27-34 49-30-5 22-19 32-49 30Z"/>
    </g>
    <g stroke="#b29759" strokeWidth="1.4" strokeLinecap="round" fill="#faf8e9">
      {[['273','99'],['331','76'],['240','159'],['205','212'],['309','184']].map(([x,y],i)=><g key={i} transform={`translate(${x} ${y})`}><path d="M0 0C-10-14-15-26-9-31 1-33 4-20 0 0ZM0 0C9-16 18-21 23-14 23-5 11-1 0 0ZM0 0C-13 8-19 18-13 24-4 26 1 12 0 0ZM0 0C9 10 16 15 23 10 25 2 11-2 0 0Z"/><circle cx="0" cy="0" r="5" fill="#c9aa67"/></g>)}
    </g>
  </svg>
}

export function AncientBookDecoration() {
  return <svg className="dashboard-ancient-book" viewBox="0 0 320 190" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <ellipse cx="173" cy="164" rx="139" ry="19" fill="#698271" fillOpacity=".14"/>
    <path d="M26 149c23-32 43-41 78-27 25 10 31 36 70 32 34-3 54-27 86-25 23 1 40 13 56 27-46 15-104 16-153 14-58-3-100 0-137-21Z" fill="#738d79" fillOpacity=".24" stroke="#4f725c" strokeOpacity=".3"/>
    <path d="M65 125 125 21l104 34-48 105-116-35Z" fill="#d1c7a7" fillOpacity=".47" stroke="#8e9c7a" strokeOpacity=".5" strokeWidth="2"/>
    <path d="M74 122 133 24l89 29-48 99-100-30Z" fill="#f4efd9" fillOpacity=".86" stroke="#969e80" strokeOpacity=".62"/>
    <path d="M79 120 137 27m-51 95 58-93m-50 95 58-93m-50 95 58-93m-49 95 58-92m-48 94 58-92m-46 94 58-92m-44 94 57-93" stroke="#9ba387" strokeOpacity=".52"/>
    <path d="m143 40 65 21m-71-12 65 21m-70-11 65 21m-71-11 65 20m-72-10 65 20m-72-10 65 20m-70-10 64 20" stroke="#627660" strokeOpacity=".27" strokeWidth="2"/>
    <path d="m50 133 95 32 75-1M52 140l91 31 75-2" stroke="#597563" strokeOpacity=".42" strokeWidth="2"/>
  </svg>
}

export function PaperPanel({children,className=''}:{children:ReactNode;className?:string}) {
  return <section className={`dashboard-paper ${className}`}><span className="dashboard-panel-branch" aria-hidden="true"/>{children}</section>
}

export function SealDecoration({children}:{children:ReactNode}) {return <span className="dashboard-panel-seal" aria-hidden="true">{children}</span>}
