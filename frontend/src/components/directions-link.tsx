import { type ReactNode } from 'react'
import { ExternalLink, Navigation } from 'lucide-react'
import './directions-link.css'

/** Opens Kakao Map directions in a new tab. Renders nothing when there is no URL. */
export function DirectionsLink({url,children,tone='solid'}:{url:string|null; children:ReactNode; tone?:'solid'|'outline'}) {
  if (!url) return null
  return <a className={`directions-link directions-${tone}`} href={url} target="_blank" rel="noopener noreferrer">
    <Navigation size={16}/><span>{children}</span><ExternalLink size={13}/><span className="sr-only"> (카카오맵 새 탭)</span>
  </a>
}
