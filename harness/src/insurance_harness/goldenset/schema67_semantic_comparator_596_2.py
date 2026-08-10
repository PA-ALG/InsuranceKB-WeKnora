"""Code-owned Schema67 reference authority and deterministic comparator.

The embedded rows contain hashes only.  They were derived once from the exact
approved 596-2 workbook; runtime never reads the workbook or a Golden file.
"""

from __future__ import annotations

import base64
import json
import zlib
from dataclasses import dataclass, field, replace
from typing import Final, Literal, cast

from insurance_harness.canonical import canonical_hash
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    CANDIDATE_SHA256,
    EXPERT_DISPLAY_NAME,
    EXPERT_PRINCIPAL_ID,
    ORDERED_FIELD_IDS,
    ORDERED_FIELD_IDS_SHA256,
    REFERENCE_BUNDLE_SNAPSHOT_SHA256,
    SCHEMA_SHA256,
    WORKBOOK_SHA256,
    SemanticAuthorityComparisonV1,
    SemanticComparatorAuthorityV1,
    semantic_authority_comparison_sha256,
    semantic_comparator_authority_sha256,
    validate_total_control_named_expert_approval_receipt,
)

TriState = Literal["present", "absent_explicitly", "unknown"]

REFERENCE_FIELDS_AUTHORITY_SHA256: Final[str] = (
    "22b5fb038b028d9901def092db1a78b7b7917aab218c243ecbc7e66ec5534fa3"
)
_EXPERT_SUBJECT_SHA256: Final[str] = (
    "b0c161f5b1e99e29dfac05552077485543aa02904f22efb9037b207558afb5ec"
)
_FIELD_OBJECT_TYPE: Final[str] = "schema67-reference-field.v1"
_FIELDS_OBJECT_TYPE: Final[str] = "schema67-reference-fields-snapshot.v1"
_REFERENCE_OBJECT_TYPE: Final[str] = "schema67-approved-reference-authority.v1"
_REFERENCE_TOKEN: Final[object] = object()
_COMPARATOR_TOKEN: Final[object] = object()

_REFERENCE_ROWS_B85: Final[str] = (
    """
c-q~4+mc+lt>wSevpoTV_wy?!92Fn{N_kwWlIzm#o{9PQSxB|)jv1fUR(8shQGE%ODl_-q1Q&p{K#=*L|Laa39-e
-7yMOja^XJp!hx?b0!nM8J{l|aaEpMx?o(e7Ewf7VoTdIh-N}WCTnJOo(#8c;Pt8kvQ#~NLom)-s4Pj~+J&#tey!
^^9@`rUureSY>Ae|)_=zw~g@)9bw~{6_u$Z*Nbp{+kED$M?w}?EYlu4?fwOzTWGTIX?aP^!!O4PXE)Nzr6hAV}JI
)i@yH(?RAg;@l(Rvo}TUWC=Yl4k^Xe|?AxEuck-W3cK%^K%cFk$?Vz_djI1u^B-_gLx=T(p+j8;Ik~@C4>)v@8&z
6Vop1Jg4x^inCgMRkEy`7#hXnp$h`RNhEy|!8Zafg45<mKt@S$}K2yD?TDMO)gHg&pHzNxU%<sn&BzY(A^EA*IwT
o3e2CAuDmIZhH5Z|NW<LAVhlVEls0AwX3$>IPIBc!tY8ZyilbuPp*dHG*ZufIL4tAFQy-Zke827&#(87^63(s@Ij
owR$2gvHnUOTDwMoP84FOTlzBHwx)Np<lU=0Q(%Ox<ZsKOn-^R%`jC&(EnWC2Z^hL&;7h_~L7>`SEGMTw7cut-+;
S-Ih<MAhrE@{lvD)W!Q$%P2X2N9C+LsFi3Od%rgTT9gxLu+fU1$0PWGw|Wl@TS^i2%?Cw)v@Zg5poT)-UdSc)%?C
a{`K+c=g04#-xqoCm$(d~fW@``-#LDKdi}F}j;qRg@c(Oq%drXm*7O`R?*9+d;4T*#roLape2odOzkL2~v$XeXme
b?QTa3f+6<7N3^!&^B8mGT^XVQ=I_~;KW-)orhehuS)fAwb!^8WMNiow60o*vIvefw@J&G!zU%gmDK9f#s4y!)5?
=ckA7j>IY5lv(aTyLv0DDy=;_gCcE{+2%5+x|)bb!wXHzm<?<Ric<D0y=4$LD*Xp3=$E%opX6Ug@^6ahqw1)vz4B
-|m)vP;PHn5Gg9Z!dY}Hp*nX~sIbxfx^tkSOFsHx%uhMQJdeKl!2sT;&`#<hK}UFNn5{t7PJ(wYN|*NrzmHU@N%b
x%9Z!MKEU?XwTOD<$nx)4+R&c+P7z$a<}lpsH&t6$)-92Rm*~E8&Ub0da|K<a1}tRmmK~5FK;XAxQ>EFQyA3y=-g
MJ6>9aj4Y8i(US0?Z<F|IVB`piug>B-v*m;Vh(eO)&TaUd?v*RMP#CF=Q5UqVZArcsWg1?%PZ;ChpcHwL*3`9TDn
$U9EtLdPH$hTQ?IgQS%r7@$HO0jN9D$(XR?}L3U5|O%8}E)p_N(h`N3_P(F7chCy0MdPC^%1)CRIx_Yq7o)3|QP|
Dzy8uEMBbwnSj|?OIjZaV8CO(4Y_L=`QHM$0}-~g)do~`%{E6PA8<s#trws%WykHT@x)_PDDlc^8_%(&!QUCe`MP
+4<ow{T_xkqo`t%9F0BrW@;i7WoK@oa47GvrVf)-*$ZV>@BBN9?tS)wk~gi2b46+h+WgFFrDZ3lcX4G|{IakUM12
E>52ZgsUZ%d|YYEh9`HP>?ofX^VDi#o44qDPg9qVW(LU4@E|W@g)U(G0O<#+w({+vdf->vIDxfktM@b+}wK^h!qE
_rq`J0+raEq$r2LzU;Q<1@G2i3PLJPDnQlwe-&N(7OQq#`<|IX{?CgMXq}i?j87HJnq!*<13X~I#I(*64Gl{kzLz
$j_^5>sU{_`cCe6T!l*SdjBtO0)1ry6xOjH%=e#?fa3`{;SB3Vs8-Y`Cccp%d;fvhwc1Rs=u78asoJR1huvb!G>D
XfsksfpOt1DO;)B3v*9!q)rSkUGSEQOT=<UmSAP!T_ZIFmjoWCBugfII@P7fG`Tg_*|c}x#VPkPR~b9-hYyq)6bs
3P8$5Ht;X5U3!k|@*VQA8wk{M`?;?6v9xdHBlh(zn#!QdJoc|V+q^03t_te=Z)@L+EYGQ4qDUIT%BCWP^=eSlivE
}+?%A`sQN%Stt0*Jbdb=U?vSgWm(;A1=y$2Wv)mv*%P?xnRht2CttPMwm!YxilyNwbhU?kOA2NKd`BeB%yd|Dbm-
0taAm^-pCqEX2>0dkEnaIg6Pom+-jwR;L#{DC1THVtF<%=t;HByLrw?s{mLjg7Z$@N52p{Ob$U3xUZh747SZnDry
w9}Tdsn@)#0rz)s5gqyMW{vlpj=G&nsnUM?$>YuF@U84_<BGM#?qJdm~68CeE6XHW*i8<OneTiiq9!u-T<Zp$2Zp
6)9yA!n%~@+n^gdMzybtl#ebCuOIKt^+BG$loEfn(<fZ-A|-aPsCc(3##W)JHbBrN%glWubyCJKvuc^FJ>`}e+%z
FQYeMvywLm;Uy&Z`!S1|QET*3R`PamG;^T(6^Hb8u9-hY?pGTj=_O_2BQiYOrp7KThl9UP(r)5EMxWGaNITD0%g+
sYMOZuPFs*O=qFPWJM2E_3{Ix#u^gzNCrbXtxd3L5Q291CcZtRBJ=g0rY*jkF6kIrqGq%djosj6HJ#EK9I|(k}_^
OQxTiX+w5h7BO|`n<&dvyjg2r5Mvz2WT~?x10;oqkUf_ci%2>{XwSlZABn5+uZK-v`<LBxdM0M@~W;^h!0phqMoE
{Ir;N6)VzO%<6!urQ&`-q=+d~ieNhsXy}X=JitGFOoM@vEZWEb!||1Tt%2&AcFxX@TbK_3t69pyimPp=MSrxb=Y0
V8{%X>iBg-yn~jvi6AFjG$Wl>CvTZBI=*t-(3c4F;P+3eZ=b(p804Clmy61Le6&Pf2V;hkCLWMOHD<X$BaMZ>dI2
R-aN35XU@V=0lv-@94b)GFHVJKk_d(47CYXVNsUE9=0&{|-D}ARxtB%qzv!KF&U-rdtFc&Z&xWa)Rq-)I7zXiA71
|9Mxl(R#9LbDYegIlA%<5`iyf%8$i7=hCx&Oj4)pk9!Sk@{PKOI#OpZ}EgbKcCK}n@|4w@yRX$+tHdbQ3f1x6DXO
TH{#q#eO1VLppP~|{6mTxs4G<buD!zEh`V#I5Kb%NLe{Zn8>uMXKW2rgDgy!A!BuqV9=)fbAlTLh0zw*QJt2$^My
#IYd<i43&_)na+`BP?`&x<^3wYH6G?O9;lu1D9UbBPrA>@z72+DmOs1jadlHX69^**A`D>1=RTQ76MJt2D>H>QNi
>4qGO@PMDS>y8?3E1se&4K(!HwKV^9di!+$S$+vxasTSipDw}t(aLz2?UGU{5L#j#865!>if)bxKmeTxlLBfWVU<
*=cY%wH+5ljcmcNa*YuNWzG~XzxfY?CBE|UybOi&)BgjW|MB%;+ZHZsaPM-+gRX2@MAUCNdH$3kU?mGHSsY6M)5s
y$g!QV2Rk22f5)f(WHGu(L`=(8wJLPfdqJIZ#0@$v_O}%*em{fZDr)k#7Vqjjh$;!wK{tOVn_sgOwv2*sQH&i+1@
ui`y=vnOBe%-b>tPCf4iXMW3D?;sKxbzW<D8y)2m?E!0!2k+GE4q_x371A&D#5UYmdGra9Opi-E68C*$MPg{GYS#
@!v1C71cu<nfjr3a+|&J)i9H-csZNl>I|A)0e%C_4%oEXeqvmV^MkqsarGfCx+Fx<L6^zA&!KL2|S<4FyVLX`}+~
ZI3aww}tpIy+Yr?)um@hUA2;GG?9P~AvS<CAX}9}2e{4^Ec*^?M_+TthiAci|J#ZF{bJE=HD}&!S(w~}q|u^V3a0
Md$`-1&nY}6a{G<)N7z<Kd!18&5>0rvi`|G@RwEfASV}a*#FFIO*)yB#-7Ip@uCA;-L+*&TaG8Lk-(zY&=3M7Xj-
gY?J5DdCS8K{5Ti>_hX8|j4^%+bCvGEzqrz!E&wLlN!ih%9TsH=8dWY+5VS3%7|>1@h9@^0|KyN`mMAUi<hr_uJ4
>u$YmG4JzFMjP4Mib7jYG5^`pX1-pblttirIV?wr!uoYqsLh(Sa-Zd<ID~(f7r-M@g!^AZ=xQaH<o=FqD3!1(`FI
QVm0s#$4qiL6xL5k;WUap*%U*4X-JmtMS!uC;uet7s&iVOH$Qi#h(YtW$fHbCH_!jL?+Wo98L0rrKANoiW_;Tp);
vy+CB-@`%A5r;6pqDNMF{<y7ggwBoKH|QsEfvZ6uIdlw|i%#i#;BJyfhB0fd@C)5_t_6Yv6eDm-r}BehOrQqO>p#
oG<$yU_xdn~G#LNLxlG&<77f2P;5Qc8+OJ~9y&NNx2E(>0V+1Qidn!DDGoAzd@!E>GFjt(6JEMsK2g)BsswojdiN
eCK!jx{OPsgd?@Da5i}^SRe2Sx-7@H|T<-B(p>mTkJ!JdA6>jb!rklHC|KS0C@(?qHVMvSe(4ZT;IwDRIMHP8pbJ
FDjUojeNZyA;Gr|`TrzGOdn3gSlWUM{VNM^3=-LG8!<zt9ukQZ@?SH!s<eR8HS^~DLZ5r^B3mA=f+EA>qmYjgI6a
`!w&?T!cvV^cB!&4L1-H~oE0SC6DUctyWf|sg$7-D>_YD!%R`f7TqYx{0Xvw>4AO)Xq>Ct0&dw3;$#V(th8{}L}}
aJ=4s1<S)PN04*3(#*BkSX|5O$V7dW+F?_KnUbT%ZLPLS&A>CL%EFALy`AccPM34h==ZUAF^$hhOR*%p5qRnxrob
4UZpAkB-4YFrD2LeLHRl1=1R_JL6)|hk+Z>IC`N#t6AD^&yDTcoun(>HC`EqWad3*5h?w-i+dh73(f`Qn7y}i7i>
&=(hsNGo6U~*?R0h5HI&D1MRaD(Lxw&2lJM1v7FszetPTmw7=g2F@1fUaJ-MEm*a<@Mf9FF@k!>GADrBiEM*B+ut
w(F?mx^3j@HrQV_uPon1pBufSooYV~xXV6un3|lMOus1>l<rz{DL8yY(NzVDe&YEl3{8lIvjIvV3;A<gXR7b@H@b
QS@7~Vjj&ddc`sj629rA@JLyB9_kjo{a3`thizm%n~3CY&y6(8x!7MweSD3>nYltAb)n+XDj!{oY-BtFZXFDAYsw
_njl*VuJhFRmYAEh&urRDQ09YPGoscq_rdplnr8Fu(W8PCsr-d@$Zrom^wjIu-btorEAR6t*jJGZ~|-1!3eS}k&Q
<z@I5G`IZ|wC$_jx*YhpmVLm5ew17-C%iz)peX^9KK>@Qz>5HEz>(Q;>6oCyE{*CVhvf~=ZTXoB!1o1%zIpetZWT
A>p)!V)`F7%ab6x40>nmXMuVp>sP&9ceSD5ipyJ)lvlZ1WFNmDwra|8qZ#U<Dy2<;~s4qVCOsbh;il)$gB!zn)9f
#D;}jOmt@g(w^QSmH5YFQ40JRG{R(kfLERu$EkSuk31wD7w4DiYwz=`#oHNt`!X&0x$}EkBAq<Z(Au%bMMOFzBO*
A{WucYbHG>>yf%D_-7r8AxDJX(vYOieHd?VV?tSv8)*43L5uhvUhXigHa7TT?Lf0?&(0A;#9d=h##ObJpDAV6S0N
+j3+L<_eg7KO0f9;wii*2s>Cd8rcB9XkQ*{=4k3HFfN}PAA4-v?z5W2Ch!;(m;Qr1`11Yk<!I@-M(4+-#v8mr772
VX?dhYyAO&7%2<)l)jKkchcgXE%X!SUci4eG>o|8)7wl|E9k2=y!=TJeWR*eCdDp1lkAX$)04EZK&RF$G0lS%o!c
Pqs<;IcH@Tgw`SX<5{6yp(PW%m?ZSfJH3ug88k;0Taos2xqAB1O0$knBn(>_l6h}Jwu2nnEnRYEk!*cTKOy?*c-C
5;Z6|fd!Dyd_Xcwz>?v5qmG>&1tLD%5pWGl%9`3)w{}R|AEuC{~v6*+)+(9VR5YbaXXrl$*(_rr5RvmHLvL&t?Nv
4*SYfd^NSwyDjz&tRbyCfZBr(HV7ad+kwm(9_<U7I)Ud59tN)YWzG*yD%H(pq>9#~$U*_&=9cdIpO(A~34C2&v7Q
Bk`TLAOeVtUrFbT6z7{+%YjA0YfSX5Yy%rmAjx${L6~J5_#u+=!qck8s20WkD5xRiTT8)u1=HE4!vB_EdBglUJo|
?){ebe}5^`0JmhE##paXqcvJpN&i0VY1rU^Jsjh*s6jXgLH<Qo}WX3m7kYzn#rHcv;orLSPy8-dA^5yzdfv~1^+V
%Z4&44ZX}GfI%uAUqnESi}e!4HqRCc*0|?a{EE4{NeNoANm7}$>nIdyml~e>veK))(jPx+k&U(!O`HETS`U=Atc9
H2Mg&`q3uTODMaj|1GR!{nD|D}vU389$EBnD2$pk~37(t4TsA1rtWn4{6DX06BppRyFq7axQrEn8B7DJxPQS^3=h
Z>~yFR>~3!s<AnWM#St-K)jC0adoCYW?ae=x=QMLD+a*^CunOe@>W$YY&lupnK5*nG)ou7#|C$H|}u6%#%C$W#im
w%rk<n)}=nnPz6=49){?IhK{tdMSEft>zjtb|c_R@FET_0K4Xv9l?~r1>u@;GyzCKH!#%Lwgs|lOAOf>nh^27OsK
^xx4rxWXBT1YXs<HH8@tl-MuyTj$!ddTLxX6I2KG=K9LHV}US5M{Y-H0;5ELEUXL<1B%#a1OS8KI^ZozUOF%5H`<
7lD2tJHzZtmR-eeSyqRsFoGGQd4w3;Swdtn6)*}Ti6;!*31lLtpE@tF(rVtKwf)|rDp_EvBr5pI0U7m;BGR8K_io
n$_Bc~h;NR&v|1yyTAU2lt%A+bh?xZQYh#nw)d*7R+ep6#JZ_~z78?{(A!mGkwl+Ydcb^h1X|2LO_ycS?7QIATvR
rLQF58H~mX}_=Ngq-5^m1;f)u%^0z5d?%(l@bxwEa5H7iu&3|3Fxbma7SBFUX-IPRyQhW)&egDq`n|bjgO;iuct4
p(_X4yslyATiMq^&|3qH1ZiTyLd|=}Yi$PF5#nLXIEg8ao~GCx=&dY4)R<6T8;*SC^VHs6@1OSl$ETOir`PCu_%&
18^V^3%Bv_BG05SC}t%X<|I=RJZIk8L4>s~x6sM{_`#fXr+Fd@ZLX>qjQSZfbx$`Gt;j3~k;yjdkC#C9Cyjf{?&o
JjUL8Bh_`&|WeUEA?4Qp&DoSrKr;YE(32^WjJiT(nef{5LmHONtarz-%IHW0@EN~y^wfU&jRLGjR!6P;b2iJ_P!J
VVGa`7G0|OCcNsc@PdaPt9PPOx{tfd2uFwT+H8!AG@7}iKp%M3ed8(Q_RB}bKp8%q*fnNYVB~Ckm{4ENEw$?CW$f
pC<qHBQfRzh!-&iAN^yjvVVsj%Z#Gam)v$1Ad}#xC-lxkc43BxTgki-y>%*FHVP{L^C`iSQW@s;AEvoiSI&;l^6z
M~yGOh@A?somml2J=<<b%Nsbf#h9@;7<253;3>I73aRwObO0&WFz<~Z1x^BoBkDVGoW);K1`pF-*gI!WjvF_~J>o
V%=zYN*Fv@=3Oq)rrixhz2>E1k=K+b#I_k(=61S&^YuyXWz2}oxHFZEdH1YhJfksLANt_j2qnh2755*};MvZg@Rf
|ym_a-h@a8uq=FCHA>Mz#~`eV$h80p757mz}BJ8;xx~-p!m~{a{xNyN1l6d&9gDydR?ge1|^qrxO#NGBv&A#a#@2
Hgu)(>F>vG7Ybvv^4&mZ6XJjkRNps>jV;91OkqB2l7mgdO6kUc*_xV5`lI(1;$`QGwL4HqMQE~*Y9Z8u4N`rm+UW
5R0U~T;h({m$8!-sw2V;N*)!n&zWBd98<EM$0C-Q3|t9pmlbw>u^HtFXq&!ywUibs8AwY=pT_k6(X!(WlRsWU+d5
v0}x3P0}<mr95l&Zp4BE7-3m8&ShB;wy^?iBY{)3VnAC?GYAs+P!P8TTOdxkYcj+#5SYGkMQDW#%^lMc45q9m#Yj
Y_C(_W*t8>(o4{RyF!bIH)<_2q$<t>iQ5-`(gaK`94*4@Fb!#>ftZoAevvKD^b^1`bbQcA~_8;G9$^l804zeM9+w
BY*Vi(ihpqiYU`Y=S}Yz&wo+%R!h>u&7$AAOW5up2lhBN)$WJE0b;TszS6o^Or+2#GF8Kko8(x349u%u|R`3?-s{
axWUXBs9hqU|25XRAU2le*u55Y8pgddOP`3fwL#a~oI^;0&=1Bh5N+WWGcDX7YA0G15^V+m0g>|ozjYO;0#=6}kZ
64hP2eh^_z>f>Xiu>rVV0I+*Ya8zi&1R4!ULrPd!DZWms{B!Z#&P7JcenGuB$kgQb1NPKHCeNHIA%;o-=|Ho9tk=
q3qVI5QLQV#~|Oow6@}Em*@Ax=gs6!WkB=p1yuOPKs&Ey1;g*a9@$&~7~*Cc1P!qOyz@8g=}ei=U+`B8f%h++KwY
h8DLn!R@%M!M8=-Lwi*snQL6t-aXvcv_(2?CrxQ^nF>2Mc`{Wo|8$$M*Wo{*{WFwt!#IVzE@#(7^IH<%PlF?l1&h
e(F#ZcsdFnxr^NI^$808lY>nW(JgMrnGkKHch@u-4a~4=e|e@Ea$-5@)f{xE4wD9VWOfROq+BFz%gb@ZPqypO(?a
F>Gh}(YxK6{ks;x1iV6PHnSao^UjHmNT^jC>F8u(BacsxvHV{2Eowp);OQ~?2cC<TT3icq7(9{P)e=!3i1#>_SfQ
5qAj<yk)>$&eGsy#b8{o0OWXQRP1XC#h1KwffZ<rz($X-D&D!~M?3*@4~&VswSy#FBT>6-SI<rr|iznlyTL%Le<q
S)7Wb$URZdRDr}kvU+rliM|!N4u=Ofiv`tYgaERZA&)juIQ*E7f0R6z;yw2HDJ;mz;M<N%;C(;l;G3^aJX`e3(U*
UqI9iV`Dy6=FU9Uj_6nPba6S@o3xR#9gU84Oez79Z=1cT||3em~9BzAf6hy%!TIxj0BhJjLNu#p}ckr3Vr1m7xkL
Pl9$N^1a(EtY(yV8UvI{#_0b<ZH~=t+e9!d1F$GqtK@mmbfGC1u9h|iLHu9->@ZB2GK%n!5DgyT%-M!uG}tZu!z3
iuhYZ%D4kd{7yIda80gnym@cLbhfmgNAPi9_YM8mO@?H!4ph9EMjvuIc^ms9X&*14ipu8BgfUSaK&mIUI@#VZU5P
b*<oA>$T#2T%Xj2ArOD<l-?ZP^KueUI*7oK%swA><CU++SnbZe{75b<i+q2q=+aqv7X)<dSN1(&5!vqd|Lsb-6af
q(qa#9u{rtVpnbk(+4?yy8m^5)p;#37L4OdEzW4PCw;s0$me==fe67RRpE&VhWOz)v;orI^BU369fF=^c7^sp-X2
jT$jE+Podz^qi<@?2x->ZUiNvv9j9^5TMv1TIHRN&CI87uWp7t%p;#-`MESvDQjzoI?9)~=l0!Awu2@TP!fj|IB9
#w@{{a&~O!fet_F>xJ4Itu1^*o=U8-X1Pl;)|o91e?MK21td)HgG7u0WCRuo3XwriB?YW?i^d!ldlA7php(guK=D
~S>2IgIW`n1#}|JW#=o)UHur57<sulVmoW`WHxB0|SNOTnh#f!GuYLO6`3vwqK0U;F7|*8<A1{Oa(bXNGc|}KuoK
G?EmVweX3PM$GoFVRG4IL_lHW6YRG|s|Hbx>F6lzrfA{A-x^9d6G3hd_CWFPAyzS^X<G-goajt+(|pnRiy9U0du=
ic(O@J&w@l1+4%T5Sx59C0Sz+-EGDxOIo}tCJjKu1YWt?{FO_8wes>u-=~XwsvTY50EzZQJyr%{Tc=x5fuQ#;&3f
CKQ|SpZEDn~5!bN<cU&r{xN*pV5U>WQhHhzab^(ueIJ20pCon83lsx7_W&F*2JUmf7GUG9zF|CfNTw@3S(RnXtJP
kz7ld0PL4D+MwC2tt0Ai7)zm`uzRh#?i|AN70tQeYaWO@i7}4x5rid^Zl=1e0@gFcU!2v_b&whe0q(MTxOmA@3qc
f{tw?=6-o
""".replace("\n", "")
)


class Schema67SemanticComparatorError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


class _ReferenceSeal(tuple[str]):
    __slots__ = ()

    def __new__(cls, token: object, authority_sha256: str) -> _ReferenceSeal:
        if token is not _REFERENCE_TOKEN:
            raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
        return tuple.__new__(cls, (authority_sha256,))


@dataclass(frozen=True, slots=True)
class ApprovedSchema67ReferenceFieldV1:
    ordinal: int
    field_id: str
    expected_state: TriState
    normalizer_id: Literal[
        "sha256-exact-utf8.v1", "not-applicable.v1"
    ]
    allowed_rendering_sha256s: tuple[str, ...]
    required_component_sha256s: tuple[str, ...]
    required_evidence_source_sha256s: tuple[str, ...]
    reference_evidence_branch_sha256s: tuple[str, ...]
    explicit_absence_quote_sha256s: tuple[str, ...]
    field_authority_sha256: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "field_id": self.field_id,
            "expected_state": self.expected_state,
            "normalizer_id": self.normalizer_id,
            "allowed_rendering_sha256s": self.allowed_rendering_sha256s,
            "required_component_sha256s": self.required_component_sha256s,
            "required_evidence_source_sha256s": self.required_evidence_source_sha256s,
            "reference_evidence_branch_sha256s": self.reference_evidence_branch_sha256s,
            "explicit_absence_quote_sha256s": self.explicit_absence_quote_sha256s,
        }


@dataclass(frozen=True, slots=True)
class ApprovedSchema67ReferenceV1:
    contract_id: Literal["schema67-approved-reference-authority.v1"]
    product_version_id: Literal["596-1"]
    review_package_id: Literal["596-2-golden-human-review"]
    workbook_sha256: str
    schema_sha256: str
    ordered_field_ids_sha256: str
    approved_candidate_sha256: str
    reference_bundle_sha256: str
    approved_by: Literal["linyao"]
    approver_principal_id: Literal["human:linyao"]
    expert_subject_sha256: str
    expert_receipt_sha256: str
    fields: tuple[ApprovedSchema67ReferenceFieldV1, ...] = field(repr=False)
    reference_fields_authority_sha256: str
    authority_sha256: str
    _factory_seal: _ReferenceSeal = field(repr=False, compare=False)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract_id": _FIELDS_OBJECT_TYPE,
            "product_version_id": self.product_version_id,
            "review_package_id": self.review_package_id,
            "workbook_sha256": self.workbook_sha256,
            "schema_sha256": self.schema_sha256,
            "ordered_field_ids_sha256": self.ordered_field_ids_sha256,
            "approved_candidate_sha256": self.approved_candidate_sha256,
            "reference_bundle_sha256": self.reference_bundle_sha256,
            "approver_principal_id": self.approver_principal_id,
            "approver_display_name": self.approved_by,
            "expert_subject_sha256": self.expert_subject_sha256,
            "fields": tuple(item.canonical_payload() for item in self.fields),
        }


def _decode_reference_rows() -> tuple[dict[str, object], ...]:
    try:
        decoded = zlib.decompress(base64.b85decode(_REFERENCE_ROWS_B85)).decode(
            "utf-8"
        )
        value = json.loads(decoded)
    except (ValueError, TypeError, UnicodeDecodeError, zlib.error):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID") from None
    if type(value) is not list or any(type(item) is not dict for item in value):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    return tuple(cast(dict[str, object], item) for item in value)


def _field_from_row(
    row: dict[str, object], expected_ordinal: int, expected_field_id: str
) -> ApprovedSchema67ReferenceFieldV1:
    try:
        allowed = tuple(cast(list[str], row["allowed_rendering_sha256s"]))
        components = tuple(cast(list[str], row["required_component_sha256s"]))
        required_sources = tuple(
            cast(list[str], row["required_evidence_source_sha256s"])
        )
        evidence_branches = tuple(
            cast(list[str], row["reference_evidence_branch_sha256s"])
        )
        absence_quotes = tuple(
            cast(list[str], row["explicit_absence_quote_sha256s"])
        )
        state = cast(TriState, row["expected_state"])
        normalizer = cast(
            Literal["sha256-exact-utf8.v1", "not-applicable.v1"],
            row["normalizer_id"],
        )
        field_id = cast(str, row["field_id"])
        ordinal = cast(int, row["ordinal"])
    except (KeyError, TypeError, ValueError):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID") from None
    hashes = (*allowed, *components, *required_sources, *evidence_branches, *absence_quotes)
    if (
        type(ordinal) is not int
        or ordinal != expected_ordinal
        or type(field_id) is not str
        or field_id != expected_field_id
        or state not in ("present", "absent_explicitly", "unknown")
        or any(value is not None and not _is_sha256(value) for value in hashes)
    ):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    if state == "unknown":
        valid_shape = (
            normalizer == "not-applicable.v1"
            and not allowed
            and not components
            and not required_sources
            and not evidence_branches
            and not absence_quotes
        )
    else:
        valid_shape = (
            normalizer == "sha256-exact-utf8.v1"
            and len(allowed) >= 1
            and len(allowed) == len(set(allowed))
            and len(components) >= 1
            and len(components) == len(set(components))
            and len(required_sources) >= 1
            and required_sources == tuple(sorted(set(required_sources)))
            and len(evidence_branches) >= 1
            and evidence_branches == tuple(sorted(set(evidence_branches)))
            and (
                len(absence_quotes) >= 1
                if state == "absent_explicitly"
                else not absence_quotes
            )
        )
    if not valid_shape:
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    provisional = ApprovedSchema67ReferenceFieldV1(
        ordinal=ordinal,
        field_id=field_id,
        expected_state=state,
        normalizer_id=normalizer,
        allowed_rendering_sha256s=allowed,
        required_component_sha256s=components,
        required_evidence_source_sha256s=required_sources,
        reference_evidence_branch_sha256s=evidence_branches,
        explicit_absence_quote_sha256s=absence_quotes,
        field_authority_sha256="0" * 64,
    )
    return replace(
        provisional,
        field_authority_sha256=canonical_hash(
            _FIELD_OBJECT_TYPE, provisional.canonical_payload()
        ),
    )


def _reference_authority_payload(
    reference: ApprovedSchema67ReferenceV1,
) -> dict[str, object]:
    return {
        "contract_id": reference.contract_id,
        "reference_fields_authority_sha256": (
            reference.reference_fields_authority_sha256
        ),
        "expert_subject_sha256": reference.expert_subject_sha256,
        "expert_receipt_sha256": reference.expert_receipt_sha256,
    }


def load_total_control_approved_schema67_reference(
    *,
    receipt: object,
    observed_at: object,
) -> ApprovedSchema67ReferenceV1:
    """Load the one code-owned workbook authority; callers provide no answers."""

    try:
        exact_receipt = validate_total_control_named_expert_approval_receipt(
            receipt=receipt,
            observed_at=observed_at,
        )
    except (TypeError, ValueError):
        raise Schema67SemanticComparatorError("REFERENCE_RECEIPT_INVALID") from None
    if exact_receipt.subject_sha256 != _EXPERT_SUBJECT_SHA256:
        raise Schema67SemanticComparatorError("REFERENCE_RECEIPT_INVALID")
    rows = _decode_reference_rows()
    if len(rows) != len(ORDERED_FIELD_IDS):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    fields = tuple(
        _field_from_row(row, ordinal, field_id)
        for ordinal, (row, field_id) in enumerate(
            zip(rows, ORDERED_FIELD_IDS, strict=True), start=1
        )
    )
    provisional = ApprovedSchema67ReferenceV1(
        contract_id="schema67-approved-reference-authority.v1",
        product_version_id="596-1",
        review_package_id="596-2-golden-human-review",
        workbook_sha256=WORKBOOK_SHA256,
        schema_sha256=SCHEMA_SHA256,
        ordered_field_ids_sha256=ORDERED_FIELD_IDS_SHA256,
        approved_candidate_sha256=CANDIDATE_SHA256,
        reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        approved_by="linyao",
        approver_principal_id="human:linyao",
        expert_subject_sha256=exact_receipt.subject_sha256,
        expert_receipt_sha256=exact_receipt.receipt_sha256,
        fields=fields,
        reference_fields_authority_sha256=REFERENCE_FIELDS_AUTHORITY_SHA256,
        authority_sha256="0" * 64,
        _factory_seal=_ReferenceSeal(_REFERENCE_TOKEN, "0" * 64),
    )
    if canonical_hash(_FIELDS_OBJECT_TYPE, provisional.canonical_payload()) != (
        REFERENCE_FIELDS_AUTHORITY_SHA256
    ):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    authority = canonical_hash(
        _REFERENCE_OBJECT_TYPE, _reference_authority_payload(provisional)
    )
    reference = replace(
        provisional,
        authority_sha256=authority,
        _factory_seal=_ReferenceSeal(_REFERENCE_TOKEN, authority),
    )
    return validate_approved_schema67_reference(reference)


def validate_approved_schema67_reference(
    reference: object,
) -> ApprovedSchema67ReferenceV1:
    if type(reference) is not ApprovedSchema67ReferenceV1:
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    if (
        type(reference._factory_seal) is not _ReferenceSeal
        or reference._factory_seal != (reference.authority_sha256,)
        or reference.workbook_sha256 != WORKBOOK_SHA256
        or reference.schema_sha256 != SCHEMA_SHA256
        or reference.ordered_field_ids_sha256 != ORDERED_FIELD_IDS_SHA256
        or reference.approved_candidate_sha256 != CANDIDATE_SHA256
        or reference.reference_bundle_sha256 != REFERENCE_BUNDLE_SNAPSHOT_SHA256
        or reference.approved_by != EXPERT_DISPLAY_NAME
        or reference.approver_principal_id != EXPERT_PRINCIPAL_ID
        or reference.expert_subject_sha256 != _EXPERT_SUBJECT_SHA256
        or tuple(item.field_id for item in reference.fields) != ORDERED_FIELD_IDS
        or any(
            item.field_authority_sha256
            != canonical_hash(_FIELD_OBJECT_TYPE, item.canonical_payload())
            for item in reference.fields
        )
        or reference.reference_fields_authority_sha256
        != REFERENCE_FIELDS_AUTHORITY_SHA256
        or canonical_hash(_FIELDS_OBJECT_TYPE, reference.canonical_payload())
        != REFERENCE_FIELDS_AUTHORITY_SHA256
        or reference.authority_sha256
        != canonical_hash(
            _REFERENCE_OBJECT_TYPE, _reference_authority_payload(reference)
        )
    ):
        raise Schema67SemanticComparatorError("REFERENCE_AUTHORITY_INVALID")
    return reference


class _ComparatorSeal(tuple[str]):
    __slots__ = ()

    def __new__(cls, token: object, authority_sha256: str) -> _ComparatorSeal:
        if token is not _COMPARATOR_TOKEN:
            raise Schema67SemanticComparatorError("COMPARATOR_FACTORY_REQUIRED")
        return tuple.__new__(cls, (authority_sha256,))


def _make_comparator_authority(
    reference: ApprovedSchema67ReferenceV1,
) -> SemanticComparatorAuthorityV1:
    provisional = SemanticComparatorAuthorityV1(
        contract_id="schema67-semantic-comparator-authority.v1",
        authority_id="total-control:linyao-schema67-semantic-comparator",
        comparator_version="schema67-explicit-authority.v1",
        workbook_sha256=WORKBOOK_SHA256,
        schema_sha256=SCHEMA_SHA256,
        ordered_field_ids_sha256=ORDERED_FIELD_IDS_SHA256,
        approved_candidate_sha256=CANDIDATE_SHA256,
        reference_bundle_sha256=REFERENCE_BUNDLE_SNAPSHOT_SHA256,
        reference_fields_authority_sha256=REFERENCE_FIELDS_AUTHORITY_SHA256,
        expert_subject_sha256=reference.expert_subject_sha256,
        expert_receipt_sha256=reference.expert_receipt_sha256,
        authority_sha256="0" * 64,
    )
    return provisional.model_copy(
        update={"authority_sha256": semantic_comparator_authority_sha256(provisional)}
    )


@dataclass(frozen=True, slots=True)
class DeterministicSchema67SemanticComparator:
    authority: SemanticComparatorAuthorityV1
    _reference: ApprovedSchema67ReferenceV1 = field(repr=False)
    _factory_seal: _ComparatorSeal = field(repr=False, compare=False)

    def compare(
        self,
        *,
        field_id: str,
        candidate_state: TriState,
        candidate_value_sha256: str | None,
        candidate_bundle_sha256: str,
    ) -> SemanticAuthorityComparisonV1:
        validate_total_control_schema67_semantic_comparator(self)
        if (
            type(field_id) is not str
            or field_id not in ORDERED_FIELD_IDS
            or candidate_state not in ("present", "absent_explicitly", "unknown")
            or not _is_sha256(candidate_bundle_sha256)
            or (
                candidate_value_sha256 is not None
                and not _is_sha256(candidate_value_sha256)
            )
            or ((candidate_state == "unknown") != (candidate_value_sha256 is None))
        ):
            raise Schema67SemanticComparatorError("CANDIDATE_INPUT_INVALID")
        reference_field = self._reference.fields[ORDERED_FIELD_IDS.index(field_id)]
        reference_value_sha256 = (
            None
            if reference_field.expected_state == "unknown"
            else reference_field.allowed_rendering_sha256s[0]
        )
        if candidate_state == "unknown" or reference_field.expected_state == "unknown":
            outcome: Literal["EQUIVALENT", "DIFFERENT", "PENDING"] = "PENDING"
        elif candidate_state != reference_field.expected_state:
            outcome = "DIFFERENT"
        elif candidate_value_sha256 in reference_field.allowed_rendering_sha256s:
            outcome = "EQUIVALENT"
        else:
            outcome = "DIFFERENT"
        provisional = SemanticAuthorityComparisonV1(
            contract_id="schema67-semantic-authority-comparison.v1",
            field_id=field_id,
            candidate_bundle_sha256=candidate_bundle_sha256,
            candidate_state=candidate_state,
            candidate_value_sha256=candidate_value_sha256,
            reference_state=reference_field.expected_state,
            reference_value_sha256=reference_value_sha256,
            required_evidence_source_sha256s=(
                reference_field.required_evidence_source_sha256s
            ),
            semantic_outcome=outcome,
            comparator_authority_sha256=self.authority.authority_sha256,
            comparison_sha256="0" * 64,
        )
        return provisional.model_copy(
            update={
                "comparison_sha256": semantic_authority_comparison_sha256(provisional)
            }
        )


def make_deterministic_schema67_semantic_comparator(
    *,
    reference: object,
) -> DeterministicSchema67SemanticComparator:
    exact_reference = validate_approved_schema67_reference(reference)
    authority = _make_comparator_authority(exact_reference)
    return DeterministicSchema67SemanticComparator(
        authority=authority,
        _reference=exact_reference,
        _factory_seal=_ComparatorSeal(_COMPARATOR_TOKEN, authority.authority_sha256),
    )


def validate_total_control_schema67_semantic_comparator(
    comparator: object,
) -> DeterministicSchema67SemanticComparator:
    if type(comparator) is not DeterministicSchema67SemanticComparator:
        raise Schema67SemanticComparatorError("COMPARATOR_AUTHORITY_INVALID")
    authority = comparator.authority
    if (
        type(comparator._factory_seal) is not _ComparatorSeal
        or comparator._factory_seal != (authority.authority_sha256,)
        or authority != _make_comparator_authority(comparator._reference)
        or comparator._reference.reference_fields_authority_sha256
        != REFERENCE_FIELDS_AUTHORITY_SHA256
    ):
        raise Schema67SemanticComparatorError("COMPARATOR_AUTHORITY_INVALID")
    validate_approved_schema67_reference(comparator._reference)
    return comparator


__all__ = [
    "ApprovedSchema67ReferenceFieldV1",
    "ApprovedSchema67ReferenceV1",
    "DeterministicSchema67SemanticComparator",
    "REFERENCE_FIELDS_AUTHORITY_SHA256",
    "Schema67SemanticComparatorError",
    "load_total_control_approved_schema67_reference",
    "make_deterministic_schema67_semantic_comparator",
    "validate_approved_schema67_reference",
    "validate_total_control_schema67_semantic_comparator",
]
